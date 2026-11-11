"""Notificaciones: plantillas, notificaciones (outbox) y entregas por canal/destinatario.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10

Requisitos: REQ-NOT-01..07, REQ-APR-08. Decisión D-NOT-001 (APROBADO).
Catálogo de eventos y política de reintentos: PROPUESTOS (PD-11, ESP-NOT).
"""

import os
import re
from collections.abc import Sequence

from alembic import context, op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# (código, asunto, cuerpo, canales). Sin datos sensibles: solo identificadores operativos.
PLANTILLAS = [
    ("APR_REQUEST_CREATED", "SecureOne: nueva solicitud #{numero}",
     "Se creó la solicitud #{numero} ({tipo}) sobre el usuario {usuario_objetivo}. "
     "Solicitante: {actor}. Revísela en Administración > Solicitudes.", "BANDEJA,CORREO"),
    ("APR_APPROVED", "SecureOne: solicitud #{numero} aprobada",
     "La solicitud #{numero} ({tipo}) sobre {usuario_objetivo} fue aprobada y aplicada por "
     "{actor}.", "BANDEJA,CORREO"),
    ("APR_REJECTED", "SecureOne: solicitud #{numero} rechazada",
     "La solicitud #{numero} ({tipo}) sobre {usuario_objetivo} fue rechazada por {actor}.",
     "BANDEJA,CORREO"),
    ("APR_CANCELLED", "SecureOne: solicitud #{numero} cancelada",
     "La solicitud #{numero} ({tipo}) sobre {usuario_objetivo} fue cancelada por {actor}.",
     "BANDEJA,CORREO"),
    ("OPS_AUDIT_OUTAGE", "SecureOne: incidente de auditoría",
     "Se registraron {incidentes} operación(es) bloqueadas por indisponibilidad de la "
     "auditoría entre {desde} y {hasta}. Revise el registro de errores.", "BANDEJA,CORREO"),
    ("NOT_DELIVERY_EXHAUSTED", "SecureOne: notificación no entregada",
     "No fue posible entregar por {canal} la notificación «{asunto_original}» tras "
     "{intentos} intentos. Revise el registro de errores.", "BANDEJA"),
]


def _role() -> str:
    role = context.config.attributes.get("app_db_user") or os.environ["APP_DB_USER"]
    if not _ROLE_RE.match(role):
        raise ValueError("APP_DB_USER inválido")
    return f'"{role}"'


def upgrade() -> None:
    role = _role()
    op.execute(
        """
        CREATE TABLE ops.plantilla_notificacion (
          codigo   varchar(40)  PRIMARY KEY,
          asunto   varchar(200) NOT NULL,
          cuerpo   text         NOT NULL,
          canales  varchar(40)  NOT NULL,
          estado   varchar(10)  NOT NULL DEFAULT 'ACTIVO' CHECK (estado IN ('ACTIVO', 'INACTIVO'))
        )
        """
    )
    for codigo, asunto, cuerpo, canales in PLANTILLAS:
        # Valores estáticos de esta migración (no hay entrada externa).
        sql = ("INSERT INTO ops.plantilla_notificacion (codigo, asunto, cuerpo, canales) "  # noqa: S608
               f"VALUES ('{codigo}', '{asunto}', '{cuerpo}', '{canales}')")
        op.execute(sql)
    op.execute(
        """
        CREATE TABLE ops.notificacion (
          id               uuid         PRIMARY KEY,
          plantilla        varchar(40)  NOT NULL REFERENCES ops.plantilla_notificacion (codigo),
          evento_origen    varchar(64)  NOT NULL,
          origen_id        varchar(64),
          asunto           varchar(200) NOT NULL,
          cuerpo           text         NOT NULL,
          clave_dedupe     varchar(200) NOT NULL UNIQUE,
          correlation_id   varchar(64),
          creada_en        timestamptz  NOT NULL DEFAULT clock_timestamp()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ops.entrega_notificacion (
          id                 uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          notificacion_id    uuid         NOT NULL REFERENCES ops.notificacion (id),
          usuario_id         uuid         NOT NULL REFERENCES app.usuario (id),
          canal              varchar(8)   NOT NULL CHECK (canal IN ('BANDEJA', 'CORREO')),
          destino            varchar(150),
          estado             varchar(10)  NOT NULL DEFAULT 'PENDIENTE'
                             CHECK (estado IN ('PENDIENTE', 'ENVIADA', 'AGOTADA')),
          intentos           smallint     NOT NULL DEFAULT 0,
          proximo_intento_en timestamptz  NOT NULL DEFAULT clock_timestamp(),
          ultimo_error       varchar(200),
          enviada_en         timestamptz,
          leida_en           timestamptz,
          UNIQUE (notificacion_id, usuario_id, canal)
        )
        """
    )
    op.execute("CREATE INDEX entrega_pendiente_idx ON ops.entrega_notificacion "
               "(proximo_intento_en) WHERE estado = 'PENDIENTE'")
    op.execute("CREATE INDEX entrega_bandeja_idx ON ops.entrega_notificacion "
               "(usuario_id, enviada_en DESC) WHERE canal = 'BANDEJA'")
    op.execute(f"GRANT SELECT ON ops.plantilla_notificacion TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON ops.notificacion TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ops.entrega_notificacion TO {role}")


def downgrade() -> None:
    op.execute("DROP TABLE ops.entrega_notificacion")
    op.execute("DROP TABLE ops.notificacion")
    op.execute("DROP TABLE ops.plantilla_notificacion")
