"""Creación de solicitudes (REQ-APR-01/03/04). Aprobación/aplicación: Fase 6.

Una solicitud guarda un ítem por atributo con su valor anterior (snapshot) y nuevo.
La BD garantiza inmutabilidad (trigger) y una sola PENDIENTE por entidad (índice único).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError
from app.core.ids import uuid7
from app.kernel.audit import AuditEntry
from app.kernel.unit_of_work import UnitOfWork
from app.modules.notifications.application.outbox import notify, request_context


@dataclass(frozen=True)
class Item:
    atributo: str
    anterior: Any
    nuevo: Any


@dataclass(frozen=True)
class CreatedRequest:
    id: uuid.UUID
    numero: int
    tipo: str
    estado: str = "PENDIENTE"


async def pending_for(s: AsyncSession, entidad: str, entidad_id: uuid.UUID) -> int | None:
    return (await s.execute(text(
        "SELECT numero FROM app.solicitud WHERE entidad = :e AND entidad_id = :i "
        "AND estado = 'PENDIENTE'"), {"e": entidad, "i": entidad_id})).scalar()


async def validate_link(s: AsyncSession, vinculada_id: uuid.UUID, entidad: str,
                        entidad_id: uuid.UUID) -> dict[str, Any]:
    """REQ-APR-06: una corrección se vincula a una solicitud CANCELADA o RECHAZADA de la misma
    entidad (la original no se modifica)."""
    link = (await s.execute(text(
        "SELECT tipo, estado, entidad, entidad_id FROM app.solicitud WHERE id = :i"),
        {"i": vinculada_id})).mappings().first()
    if link is None or link["entidad"] != entidad or link["entidad_id"] != entidad_id:
        raise BusinessRuleError("La solicitud vinculada no existe o es de otra entidad.")
    if link["estado"] not in ("CANCELADA", "RECHAZADA"):
        raise BusinessRuleError("Solo se vincula a una solicitud cancelada o rechazada.")
    return dict(link)


async def create_request(
    uow: UnitOfWork, *, tipo: str, entidad: str, entidad_id: uuid.UUID,
    solicitante_id: uuid.UUID | None, items: list[Item], motivo: str | None = None,
    origen: str = "MANUAL", vinculada_id: uuid.UUID | None = None,
) -> CreatedRequest:
    s = uow.session
    if vinculada_id is not None:
        await validate_link(s, vinculada_id, entidad, entidad_id)
    existing = await pending_for(s, entidad, entidad_id)
    if existing is not None:
        raise ConflictError("Ya existe una solicitud pendiente sobre este registro.",
                            details={"solicitud_pendiente": existing})
    rid = uuid7()
    try:
        async with s.begin_nested():
            numero = (await s.execute(text(
                "INSERT INTO app.solicitud (id, tipo, origen, entidad, entidad_id, motivo, "
                "solicitante_id, solicitud_vinculada_id) VALUES (:id, :t, :o, :e, :ei, :m, :s, :v) "
                "RETURNING numero"),
                {"id": rid, "t": tipo, "o": origen, "e": entidad, "ei": entidad_id,
                 "m": motivo, "s": solicitante_id, "v": vinculada_id})).scalar_one()
    except IntegrityError as exc:  # carrera con otra solicitud pendiente
        raise ConflictError("Ya existe una solicitud pendiente sobre este registro.") from exc
    for orden, it in enumerate(items, start=1):
        await s.execute(text(
            "INSERT INTO app.solicitud_item (solicitud_id, orden, atributo, valor_anterior, "
            "valor_nuevo) VALUES (:s, :o, :a, CAST(:va AS jsonb), CAST(:vn AS jsonb))"),
            {"s": rid, "o": orden, "a": it.atributo,
             "va": _json(it.anterior), "vn": _json(it.nuevo)})
    uow.audit(AuditEntry(
        categoria="APROBACIONES", accion="APR_REQUEST_CREATED", modulo="ADM",
        entidad="solicitud", entidad_id=str(rid), solicitud_id=rid, motivo=motivo,
        valor_nuevo={it.atributo: it.nuevo for it in items},
        valor_anterior={it.atributo: it.anterior for it in items},
        detalle={"numero": numero, "tipo": tipo, "entidad": entidad,
                 "entidad_id": str(entidad_id)},
    ))
    # REQ-APR-08: ambos administradores reciben la notificación (outbox, D-NOT-001).
    actor = uow.ctx.actor_usuario_red or ("Talento Humano" if origen == "TH" else None)
    await notify(uow, "APR_REQUEST_CREATED", str(rid), await request_context(s, rid, actor))
    return CreatedRequest(rid, numero, tipo)


def _json(value: Any) -> str | None:
    import json

    return None if value is None else json.dumps(value, default=str)
