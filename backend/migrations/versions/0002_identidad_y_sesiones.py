"""Identidad mínima y sesiones (Fase 3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10

Requisitos: REQ-AUTH-01..12, REQ-IAM-01 (perfil único), REQ-USER-04, REQ-USER-14.
Decisiones: PD-01 y PD-06 (APROBADAS); PD-02, PD-07 interino y PD-14 (PROPUESTAS).
Sin campo Empresa (REQ-USER-03). Sin borrado físico (estados).
"""

import os
import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _role() -> str:
    role = context.config.attributes.get("app_db_user") or os.environ["APP_DB_USER"]
    if not _ROLE_RE.match(role):
        raise ValueError("APP_DB_USER inválido")
    return f'"{role}"'


def upgrade() -> None:
    role = _role()

    op.execute(
        """
        CREATE TABLE app.perfil (
          id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          codigo          varchar(40)  NOT NULL UNIQUE,
          nombre          varchar(100) NOT NULL,
          descripcion     text,
          estado          varchar(10)  NOT NULL DEFAULT 'ACTIVO'
                          CHECK (estado IN ('ACTIVO', 'INACTIVO')),
          es_sistema      boolean      NOT NULL DEFAULT false,
          creado_en       timestamptz  NOT NULL DEFAULT now(),
          modificado_en   timestamptz,
          inhabilitado_en timestamptz
        )
        """
    )
    op.execute(
        "INSERT INTO app.perfil (codigo, nombre, descripcion, es_sistema) VALUES "
        "('ADMINISTRADOR', 'Administrador', "
        "'Perfil de sistema protegido (PD-06). Máximo dos usuarios activos.', true)"
    )

    # Usuario de red: minúsculas; 8 caracteres alternados letra/número (lectura literal; PD-07).
    op.execute(
        r"""
        CREATE TABLE app.usuario (
          id                uuid         PRIMARY KEY,
          usuario_red       varchar(8)   NOT NULL UNIQUE
                            CHECK (usuario_red ~ '^([a-z][0-9]){4}$|^([0-9][a-z]){4}$'),
          identificacion    varchar(20)  NOT NULL UNIQUE
                            CHECK (identificacion ~ '^[A-Za-z0-9-]{3,20}$'),
          nombre            varchar(100) NOT NULL,
          primer_apellido   varchar(50)  NOT NULL,
          segundo_apellido  varchar(50),
          correo            varchar(150) NOT NULL,
          perfil_id         uuid         NOT NULL REFERENCES app.perfil (id),
          tipo_alta         varchar(12)  CHECK (tipo_alta IN ('NORMAL', 'EXCEPCIONAL')),
          estado            varchar(16)  NOT NULL
                            CHECK (estado IN ('PENDIENTE_ALTA', 'ACTIVO', 'INACTIVO')),
          ultimo_ingreso    timestamptz,
          ultima_actividad  timestamptz,
          creado_en         timestamptz  NOT NULL DEFAULT now(),
          creado_por        uuid,
          modificado_en     timestamptz,
          modificado_por    uuid
        )
        """
    )
    op.execute("CREATE INDEX usuario_perfil_idx ON app.usuario (perfil_id)")

    # Máximo dos administradores activos (D-ADMIN-001 / PD-06), garantizado en BD.
    op.execute(
        """
        CREATE FUNCTION app.validar_max_admins() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          admin_id uuid;
          n int;
        BEGIN
          SELECT id INTO admin_id FROM app.perfil WHERE codigo = 'ADMINISTRADOR';
          IF NEW.estado = 'ACTIVO' AND NEW.perfil_id = admin_id THEN
            PERFORM pg_advisory_xact_lock(7302261002);
            SELECT count(*) INTO n FROM app.usuario
             WHERE estado = 'ACTIVO' AND perfil_id = admin_id AND id <> NEW.id;
            IF n >= 2 THEN
              RAISE EXCEPTION 'máximo dos administradores activos'
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER usuario_max_admins BEFORE INSERT OR UPDATE OF estado, perfil_id "
        "ON app.usuario FOR EACH ROW EXECUTE FUNCTION app.validar_max_admins()"
    )

    op.execute(
        """
        CREATE TABLE app.credencial (
          usuario_id         uuid         PRIMARY KEY REFERENCES app.usuario (id),
          password_hash      varchar(255) NOT NULL,
          debe_cambiar       boolean      NOT NULL,
          intentos_fallidos  smallint     NOT NULL DEFAULT 0 CHECK (intentos_fallidos >= 0),
          bloqueado_hasta    timestamptz,
          cambiada_en        timestamptz  NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE app.historial_contrasena (
          id             uuid         PRIMARY KEY,
          usuario_id     uuid         NOT NULL REFERENCES app.usuario (id),
          password_hash  varchar(255) NOT NULL,
          creada_en      timestamptz  NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX historial_contrasena_usuario_idx "
        "ON app.historial_contrasena (usuario_id, creada_en DESC)"
    )
    # Tabla técnica: se purgan hashes más antiguos que las últimas 5 (PD-02, minimización).
    op.execute(f"GRANT DELETE ON app.historial_contrasena TO {role}")

    op.execute(
        """
        CREATE TABLE app.sesion (
          id                uuid         PRIMARY KEY,
          usuario_id        uuid         NOT NULL REFERENCES app.usuario (id),
          iniciada_en       timestamptz  NOT NULL DEFAULT now(),
          ultima_actividad  timestamptz  NOT NULL DEFAULT now(),
          finalizada_en     timestamptz,
          motivo_fin        varchar(24)  CHECK (motivo_fin IN (
                              'LOGOUT', 'INACTIVIDAD', 'REEMPLAZADA', 'INHABILITACION',
                              'REVOCADA_ADMIN', 'REUSO_REFRESH', 'CAMBIO_CONTRASENA')),
          restringida       boolean      NOT NULL DEFAULT false,
          ip                inet,
          user_agent        varchar(512),
          CHECK ((finalizada_en IS NULL) = (motivo_fin IS NULL))
        )
        """
    )
    # Una sola sesión abierta por usuario (REQ-AUTH-09).
    op.execute(
        "CREATE UNIQUE INDEX sesion_una_activa_idx ON app.sesion (usuario_id) "
        "WHERE finalizada_en IS NULL"
    )
    op.execute("CREATE INDEX sesion_usuario_idx ON app.sesion (usuario_id, iniciada_en DESC)")

    op.execute(
        """
        CREATE TABLE app.refresh_token (
          id              uuid         PRIMARY KEY,
          sesion_id       uuid         NOT NULL REFERENCES app.sesion (id),
          familia_id      uuid         NOT NULL,
          token_hash      bytea        NOT NULL UNIQUE,
          emitido_en      timestamptz  NOT NULL DEFAULT now(),
          usado_en        timestamptz,
          revocado_en     timestamptz,
          reemplazado_por uuid
        )
        """
    )
    op.execute("CREATE INDEX refresh_token_sesion_idx ON app.refresh_token (sesion_id)")


def downgrade() -> None:
    for table in ("refresh_token", "sesion", "historial_contrasena", "credencial"):
        op.execute(f"DROP TABLE app.{table}")
    op.execute("DROP TABLE app.usuario")
    op.execute("DROP FUNCTION app.validar_max_admins()")
    op.execute("DROP TABLE app.perfil")
