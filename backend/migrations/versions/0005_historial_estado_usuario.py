"""Historial de estados del usuario (solo inserción).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10

Requisitos: REQ-USER-08 (conservar historial, actor, fecha y motivo), REQ-AUTH-10/11.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.usuario_estado_historial (
          id               uuid         PRIMARY KEY,
          usuario_id       uuid         NOT NULL REFERENCES app.usuario (id),
          estado_anterior  varchar(16),
          estado_nuevo     varchar(16)  NOT NULL,
          motivo           text         NOT NULL,
          actor_id         uuid         REFERENCES app.usuario (id),
          solicitud_id     uuid         REFERENCES app.solicitud (id),
          ocurrido_en      timestamptz  NOT NULL DEFAULT clock_timestamp()
        )
        """
    )
    op.execute("CREATE INDEX usuario_estado_historial_usuario_idx "
               "ON app.usuario_estado_historial (usuario_id, ocurrido_en)")
    op.execute(
        """
        CREATE FUNCTION app.historial_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'el historial de estados no se modifica'
            USING ERRCODE = 'check_violation';
        END $$
        """
    )
    op.execute("CREATE TRIGGER usuario_estado_historial_inmutable BEFORE UPDATE "
               "ON app.usuario_estado_historial FOR EACH ROW "
               "EXECUTE FUNCTION app.historial_inmutable()")


def downgrade() -> None:
    op.execute("DROP TABLE app.usuario_estado_historial")
    op.execute("DROP FUNCTION app.historial_inmutable()")
