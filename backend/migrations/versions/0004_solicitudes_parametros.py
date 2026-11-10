"""Solicitudes de aprobación, ítems por atributo y parámetros generales.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10

Requisitos: REQ-APR-01, 03, 04, 05, 06, 09; REQ-USER-07; REQ-TH-06 (parámetro).
Decisiones: PD-05 (APROBADO). Estados SUPERADA y regla de una pendiente por entidad: PROPUESTOS.
"""

import os
import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

TIPOS = ("ALTA_USUARIO", "MODIFICACION_USUARIO", "MODULOS_USUARIO", "INHABILITACION_USUARIO",
         "REACTIVACION_USUARIO")
ESTADOS = ("PENDIENTE", "APROBADA", "RECHAZADA", "CANCELADA", "SUPERADA")


def _role() -> str:
    role = context.config.attributes.get("app_db_user") or os.environ["APP_DB_USER"]
    if not _ROLE_RE.match(role):
        raise ValueError("APP_DB_USER inválido")
    return f'"{role}"'


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    role = _role()

    op.execute(
        f"""
        CREATE TABLE app.solicitud (
          id                     uuid         PRIMARY KEY,
          numero                 bigint       GENERATED ALWAYS AS IDENTITY UNIQUE,
          tipo                   varchar(32)  NOT NULL CHECK (tipo IN ({_in(TIPOS)})),
          origen                 varchar(8)   NOT NULL CHECK (origen IN ('MANUAL', 'TH')),
          entidad                varchar(32)  NOT NULL,
          entidad_id             uuid         NOT NULL,
          estado                 varchar(12)  NOT NULL DEFAULT 'PENDIENTE'
                                 CHECK (estado IN ({_in(ESTADOS)})),
          motivo                 text,
          solicitante_id         uuid         REFERENCES app.usuario (id),
          creada_en              timestamptz  NOT NULL DEFAULT now(),
          resuelta_por_id        uuid         REFERENCES app.usuario (id),
          resuelta_en            timestamptz,
          motivo_resolucion      text,
          solicitud_vinculada_id uuid         REFERENCES app.solicitud (id),
          CHECK (origen = 'TH' OR solicitante_id IS NOT NULL),
          CHECK ((estado = 'PENDIENTE') = (resuelta_en IS NULL))
        )
        """
    )
    # Una sola solicitud PENDIENTE por entidad (ESP-ADM-USR R4, PROPUESTO).
    op.execute(
        "CREATE UNIQUE INDEX solicitud_una_pendiente_idx ON app.solicitud (entidad, entidad_id) "
        "WHERE estado = 'PENDIENTE'"
    )
    op.execute("CREATE INDEX solicitud_estado_idx ON app.solicitud (estado, creada_en DESC)")

    # REQ-APR-06: una solicitud enviada no se modifica silenciosamente. Solo se permite la
    # transición única PENDIENTE → resuelta, completando los campos de resolución.
    op.execute(
        """
        CREATE FUNCTION app.solicitud_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.estado <> 'PENDIENTE' THEN
            RAISE EXCEPTION 'la solicitud % ya fue resuelta', OLD.numero
              USING ERRCODE = 'check_violation';
          END IF;
          IF (NEW.id, NEW.numero, NEW.tipo, NEW.origen, NEW.entidad, NEW.entidad_id, NEW.motivo,
              NEW.solicitante_id, NEW.creada_en, NEW.solicitud_vinculada_id)
             IS DISTINCT FROM
             (OLD.id, OLD.numero, OLD.tipo, OLD.origen, OLD.entidad, OLD.entidad_id, OLD.motivo,
              OLD.solicitante_id, OLD.creada_en, OLD.solicitud_vinculada_id) THEN
            RAISE EXCEPTION 'una solicitud enviada no se modifica'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER solicitud_inmutable BEFORE UPDATE ON app.solicitud "
        "FOR EACH ROW EXECUTE FUNCTION app.solicitud_inmutable()"
    )

    op.execute(
        """
        CREATE TABLE app.solicitud_item (
          id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
          solicitud_id    uuid        NOT NULL REFERENCES app.solicitud (id),
          orden           smallint    NOT NULL,
          atributo        varchar(40) NOT NULL,
          valor_anterior  jsonb,
          valor_nuevo     jsonb,
          UNIQUE (solicitud_id, atributo)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION app.solicitud_item_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'los ítems de una solicitud no se modifican'
            USING ERRCODE = 'check_violation';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER solicitud_item_inmutable BEFORE UPDATE ON app.solicitud_item "
        "FOR EACH ROW EXECUTE FUNCTION app.solicitud_item_inmutable()"
    )

    op.execute(
        """
        CREATE TABLE ops.parametro (
          clave          varchar(64)  PRIMARY KEY,
          valor          text,
          tipo           varchar(8)   NOT NULL CHECK (tipo IN ('ENTERO', 'HORA', 'TEXTO')),
          descripcion    text         NOT NULL,
          minimo         integer,
          maximo         integer,
          modificado_en  timestamptz,
          modificado_por uuid
        )
        """
    )
    op.execute(
        "INSERT INTO ops.parametro (clave, valor, tipo, descripcion, minimo, maximo) VALUES "
        "('th.umbral_alerta_horas', '4', 'ENTERO', 'Horas tras la hora habitual para alertar "
        "que el archivo diario de planta activa no llegó (D-TH-003).', 1, 72), "
        "('th.hora_habitual', NULL, 'HORA', 'Hora habitual de llegada del archivo diario de "
        "planta activa (HH:MM). Sin valor por defecto: la define el administrador.', NULL, NULL)"
    )
    op.execute(f"GRANT SELECT, UPDATE ON ops.parametro TO {role}")


def downgrade() -> None:
    op.execute("DROP TABLE ops.parametro")
    op.execute("DROP TABLE app.solicitud_item")
    op.execute("DROP TABLE app.solicitud")
    op.execute("DROP FUNCTION app.solicitud_item_inmutable()")
    op.execute("DROP FUNCTION app.solicitud_inmutable()")
