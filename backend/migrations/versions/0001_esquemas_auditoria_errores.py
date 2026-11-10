"""Esquemas base, auditoría inmutable encadenada y registro de errores.

Revision ID: 0001
Revises:
Create Date: 2026-11-09

Requisitos: REQ-AUD-02, REQ-AUD-03, REQ-AUD-04, REQ-AUD-07, REQ-ERR-01, REQ-ERR-02, REQ-RNF-04.
Decisión: PD-03 (PROPUESTO) — mismo PostgreSQL, esquema `audit` aislado, rol de runtime solo
con INSERT/SELECT, triggers anti UPDATE/DELETE/TRUNCATE y cadena de hash calculada en BD.
"""

import os
import re
from collections.abc import Sequence

from alembic import context, op


def app_db_user() -> str:
    return context.config.attributes.get("app_db_user") or os.environ["APP_DB_USER"]


revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _role() -> str:
    role = app_db_user()
    if not _ROLE_RE.match(role):
        raise ValueError("APP_DB_USER inválido: use minúsculas, dígitos y '_' (máx. 63)")
    return f'"{role}"'


def upgrade() -> None:
    role = _role()

    # ---------------------------------------------------------------- base de datos y esquemas
    op.execute(
        f"""
        DO $$
        BEGIN
          EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
          EXECUTE format('GRANT CONNECT ON DATABASE %I TO {role}', current_database());
        END $$;
        """
    )
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    for schema in ("app", "audit", "ops"):
        op.execute(f"CREATE SCHEMA {schema}")
        op.execute(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC")
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
    op.execute(f"GRANT SELECT ON public.alembic_version TO {role}")

    # Tablas futuras de `app`: lectura/alta/edición; SIN DELETE (regla 11: sin borrado físico).
    # Si una tabla técnica necesita DELETE, la migración que la cree lo otorgará explícitamente.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE ON TABLES TO {role}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO {role}"
    )

    # ---------------------------------------------------------------- auditoría
    op.execute("CREATE SEQUENCE audit.evento_seq")
    op.execute(
        """
        CREATE TABLE audit.evento (
          seq               bigint       PRIMARY KEY,
          id                uuid         NOT NULL UNIQUE,
          ocurrido_en       timestamptz  NOT NULL,
          actor_id          uuid,
          actor_usuario_red varchar(64),
          actor_tipo        varchar(16)  NOT NULL
                            CHECK (actor_tipo IN ('USUARIO', 'SISTEMA', 'TH')),
          categoria         varchar(32)  NOT NULL,
          modulo            varchar(16),
          accion            varchar(64)  NOT NULL,
          entidad           varchar(64),
          entidad_id        varchar(64),
          valor_anterior    jsonb,
          valor_nuevo       jsonb,
          resultado         varchar(16)  NOT NULL
                            CHECK (resultado IN ('EXITO', 'FALLO', 'DENEGADO')),
          motivo            text,
          ip_origen         inet,
          user_agent        varchar(512),
          detalle           jsonb,
          correlation_id    varchar(64),
          solicitud_id      uuid,
          hash_previo       bytea,
          hash              bytea        NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX evento_ocurrido_idx ON audit.evento (ocurrido_en DESC)")
    op.execute("CREATE INDEX evento_entidad_idx ON audit.evento (entidad, entidad_id)")
    op.execute("CREATE INDEX evento_actor_idx ON audit.evento (actor_id)")
    op.execute("CREATE INDEX evento_correlation_idx ON audit.evento (correlation_id)")

    # Contenido canónico: independiente de la zona horaria de la sesión.
    op.execute(
        """
        CREATE FUNCTION audit.contenido_canonico(e audit.evento) RETURNS text
        LANGUAGE sql STABLE AS $$
          SELECT jsonb_build_object(
            'id', e.id,
            'ts', to_char(e.ocurrido_en AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            'actor_id', e.actor_id, 'actor_usuario_red', e.actor_usuario_red,
            'actor_tipo', e.actor_tipo, 'categoria', e.categoria, 'modulo', e.modulo,
            'accion', e.accion, 'entidad', e.entidad, 'entidad_id', e.entidad_id,
            'valor_anterior', e.valor_anterior, 'valor_nuevo', e.valor_nuevo,
            'resultado', e.resultado, 'motivo', e.motivo,
            'ip_origen', host(e.ip_origen), 'user_agent', e.user_agent,
            'detalle', e.detalle, 'correlation_id', e.correlation_id,
            'solicitud_id', e.solicitud_id
          )::text
        $$
        """
    )

    # Encadenamiento: serializado por advisory lock; seq, fecha y hash los fija la BD
    # (el cliente no puede falsearlos).
    op.execute(
        """
        CREATE FUNCTION audit.encadenar() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
          prev bytea;
        BEGIN
          PERFORM pg_advisory_xact_lock(7302261001);
          SELECT hash INTO prev FROM audit.evento ORDER BY seq DESC LIMIT 1;
          NEW.seq := nextval('audit.evento_seq');
          NEW.ocurrido_en := clock_timestamp();
          NEW.hash_previo := prev;
          NEW.hash := sha256(
            coalesce(prev, ''::bytea) || convert_to(audit.contenido_canonico(NEW), 'UTF8')
          );
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER evento_encadenar BEFORE INSERT ON audit.evento "
        "FOR EACH ROW EXECUTE FUNCTION audit.encadenar()"
    )

    op.execute(
        """
        CREATE FUNCTION audit.bloquear_modificacion() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit.evento es inmutable (% bloqueado)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER evento_inmutable BEFORE UPDATE OR DELETE ON audit.evento "
        "FOR EACH ROW EXECUTE FUNCTION audit.bloquear_modificacion()"
    )
    op.execute(
        "CREATE TRIGGER evento_no_truncate BEFORE TRUNCATE ON audit.evento "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit.bloquear_modificacion()"
    )

    op.execute(
        """
        CREATE FUNCTION audit.verificar_cadena(OUT total bigint, OUT primer_seq_invalido bigint)
        LANGUAGE plpgsql STABLE AS $$
        DECLARE
          r audit.evento;
          prev bytea := NULL;
        BEGIN
          total := 0;
          primer_seq_invalido := NULL;
          FOR r IN SELECT * FROM audit.evento ORDER BY seq LOOP
            total := total + 1;
            IF primer_seq_invalido IS NULL AND (
                 r.hash_previo IS DISTINCT FROM prev
                 OR r.hash <> sha256(coalesce(prev, ''::bytea)
                                     || convert_to(audit.contenido_canonico(r), 'UTF8'))
               ) THEN
              primer_seq_invalido := r.seq;
            END IF;
            prev := r.hash;
          END LOOP;
        END $$
        """
    )

    op.execute(f"GRANT SELECT, INSERT ON audit.evento TO {role}")
    op.execute(f"GRANT USAGE ON SEQUENCE audit.evento_seq TO {role}")
    op.execute(f"GRANT EXECUTE ON FUNCTION audit.verificar_cadena() TO {role}")

    # ---------------------------------------------------------------- registro de errores
    op.execute(
        """
        CREATE TABLE ops.registro_error (
          id               uuid         PRIMARY KEY,
          ocurrido_en      timestamptz  NOT NULL DEFAULT clock_timestamp(),
          categoria        varchar(32)  NOT NULL CHECK (categoria IN (
                             'AUTENTICACION', 'VALIDACION', 'CRUD', 'AUTOMATIZACION',
                             'NOTIFICACION', 'INTEGRACION', 'BASE_DATOS', 'INFRAESTRUCTURA',
                             'RESPALDO', 'RECUPERACION', 'AUDITORIA')),
          modulo           varchar(16),
          componente       varchar(64)  NOT NULL,
          actor_id         uuid,
          proceso          varchar(64),
          tipo             varchar(128) NOT NULL,
          severidad        varchar(8)   NOT NULL
                           CHECK (severidad IN ('BAJA', 'MEDIA', 'ALTA', 'CRITICA')),
          descripcion      text         NOT NULL,
          diagnostico      jsonb,
          estado_atencion  varchar(16)  NOT NULL DEFAULT 'ABIERTO'
                           CHECK (estado_atencion IN ('ABIERTO', 'EN_ATENCION', 'CERRADO')),
          correlation_id   varchar(64),
          atendido_por     uuid,
          atendido_en      timestamptz
        )
        """
    )
    op.execute("CREATE INDEX registro_error_ocurrido_idx ON ops.registro_error (ocurrido_en DESC)")
    op.execute("CREATE INDEX registro_error_estado_idx ON ops.registro_error (estado_atencion)")
    op.execute("CREATE INDEX registro_error_corr_idx ON ops.registro_error (correlation_id)")
    # Sin DELETE: los errores se atienden (estado), no se borran.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ops.registro_error TO {role}")


def downgrade() -> None:
    # Solo para desarrollo: destruye toda la historia. No usar en ambientes con datos reales.
    op.execute("DROP SCHEMA ops CASCADE")
    op.execute("DROP SCHEMA audit CASCADE")
    op.execute("DROP SCHEMA app CASCADE")
