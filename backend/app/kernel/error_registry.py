"""Registro centralizado de errores (REQ-ERR-01/02), independiente de la auditoría.

Se escribe en su PROPIA transacción (la operación que falló pudo haber abortado la suya).
Nunca lanza excepciones: si no puede registrar, deja constancia en el log operativo.
"""

import logging
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import uuid7
from app.core.logging import correlation_id_var, redact
from app.kernel.models import ops_registro_error

logger = logging.getLogger(__name__)

Categoria = Literal[
    "AUTENTICACION", "VALIDACION", "CRUD", "AUTOMATIZACION", "NOTIFICACION", "INTEGRACION",
    "BASE_DATOS", "INFRAESTRUCTURA", "RESPALDO", "RECUPERACION", "AUDITORIA",
]
Severidad = Literal["BAJA", "MEDIA", "ALTA", "CRITICA"]


def classify(exc: BaseException) -> Categoria:
    if isinstance(exc, OperationalError | InterfaceError | DBAPIError):
        return "BASE_DATOS"
    return "INFRAESTRUCTURA"


async def record_error(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    categoria: Categoria,
    componente: str,
    tipo: str,
    descripcion: str,
    severidad: Severidad = "ALTA",
    modulo: str | None = None,
    actor_id: UUID | None = None,
    proceso: str | None = None,
    diagnostico: dict[str, Any] | None = None,
) -> UUID | None:
    error_id = uuid7()
    try:
        async with sessionmaker() as session, session.begin():
            await session.execute(
                insert(ops_registro_error).values(
                    id=error_id,
                    categoria=categoria,
                    modulo=modulo,
                    componente=componente[:64],
                    actor_id=actor_id,
                    proceso=proceso,
                    tipo=tipo[:128],
                    severidad=severidad,
                    descripcion=str(redact(descripcion)),
                    diagnostico=redact(diagnostico) if diagnostico else None,
                    correlation_id=correlation_id_var.get(),
                )
            )
        return error_id
    except Exception as exc:  # noqa: BLE001 - el registro de errores nunca debe romper la respuesta
        logger.error("no se pudo registrar el error en ops.registro_error (%s)", type(exc).__name__)
        return None
