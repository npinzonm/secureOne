"""Registro de respaldos y restauraciones.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-11

Requisitos: REQ-RNF-08 / M §15.1 (registro de operaciones de respaldo y recuperación).
Lo escribe el servicio `backup` con el rol owner; el backend solo puede leerlo.
"""

import os
import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role = context.config.attributes.get("app_db_user") or os.environ["APP_DB_USER"]
    if not re.match(r"^[a-z_][a-z0-9_]{0,62}$", role):
        raise ValueError("APP_DB_USER inválido")
    op.execute(
        """
        CREATE TABLE ops.registro_respaldo (
          id         uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          tipo       varchar(14)  NOT NULL CHECK (tipo IN
                       ('DIARIO', 'SEMANAL', 'MENSUAL', 'MANUAL', 'RESTAURACION')),
          archivo    varchar(300) NOT NULL,
          sha256     char(64),
          tamano     bigint,
          inicio     timestamptz  NOT NULL,
          fin        timestamptz  NOT NULL DEFAULT now(),
          resultado  varchar(6)   NOT NULL CHECK (resultado IN ('EXITO', 'FALLO')),
          detalle    text
        )
        """
    )
    op.execute(f'GRANT SELECT ON ops.registro_respaldo TO "{role}"')


def downgrade() -> None:
    op.execute("DROP TABLE ops.registro_respaldo")
