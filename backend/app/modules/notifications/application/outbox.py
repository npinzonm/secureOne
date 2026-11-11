"""Generación de notificaciones (patrón outbox; REQ-NOT-01..07, REQ-APR-08, D-NOT-001).

- Se genera DENTRO de la transacción de la operación, en un savepoint: si la generación falla,
  se descarta solo el savepoint y la operación (ya auditada) continúa. El fallo se registra en
  `ops.registro_error` tras el commit.
- Destinatarios OBLIGATORIOS: todos los usuarios activos con perfil ADMINISTRADOR (calculados
  aquí; no existe forma de editarlos). Una entrega por canal y destinatario.
- Sin datos sensibles: el contexto se limita a identificadores operativos.
"""

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.logging import correlation_id_var, redact
from app.kernel.error_registry import record_error
from app.kernel.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)
MAX_FIELD = 200


def render(template: str, context: dict[str, Any]) -> str:
    """Formato seguro: claves ausentes → «-», valores saneados y acotados."""
    safe = defaultdict(lambda: "-", {
        k: str(redact({k: v})[k])[:MAX_FIELD] if v is not None else "-"
        for k, v in context.items()
    })
    return template.format_map(safe)


async def generate(
    session: AsyncSession, plantilla: str, origen_id: str, context: dict[str, Any],
    dedupe: str | None = None,
) -> bool:
    """Genera la notificación y sus entregas. Nunca lanza: devuelve False si no pudo."""
    try:
        async with session.begin_nested():
            tpl = (await session.execute(text(
                "SELECT asunto, cuerpo, canales FROM ops.plantilla_notificacion "
                "WHERE codigo = :c AND estado = 'ACTIVO'"), {"c": plantilla})).first()
            if tpl is None:
                return True  # plantilla desactivada: no se notifica (decisión administrativa)
            nid = uuid7()
            inserted = (await session.execute(text(
                "INSERT INTO ops.notificacion (id, plantilla, evento_origen, origen_id, asunto, "
                "cuerpo, clave_dedupe, correlation_id) VALUES (:id, :p, :e, :o, :a, :b, :d, :c) "
                "ON CONFLICT (clave_dedupe) DO NOTHING RETURNING id"),
                {"id": nid, "p": plantilla, "e": plantilla, "o": origen_id,
                 "a": render(tpl[0], context)[:200], "b": render(tpl[1], context),
                 "d": dedupe or f"{plantilla}:{origen_id}", "c": correlation_id_var.get()},
            )).scalar()
            if inserted is None:
                return True  # control de duplicados (REQ-NOT-07)
            await session.execute(text(
                """
                INSERT INTO ops.entrega_notificacion (notificacion_id, usuario_id, canal, destino)
                SELECT :n, u.id, c.canal, CASE WHEN c.canal = 'CORREO' THEN u.correo END
                  FROM app.usuario u
                  JOIN app.perfil pf ON pf.id = u.perfil_id
                 CROSS JOIN unnest(CAST(:canales AS text[])) AS c(canal)
                 WHERE pf.codigo = 'ADMINISTRADOR' AND u.estado = 'ACTIVO'
                """),
                {"n": nid, "canales": tpl[2].split(",")})
        return True
    except Exception as exc:  # noqa: BLE001 - D-NOT-001: nunca revierte la operación
        logger.error("no se pudo generar la notificación %s (%s)", plantilla,
                     type(exc).__name__)
        return False


async def notify(uow: UnitOfWork, plantilla: str, origen_id: str,
                 context: dict[str, Any], dedupe: str | None = None) -> None:
    if await generate(uow.session, plantilla, origen_id, context, dedupe):
        return
    sm = uow.sessionmaker

    async def _record() -> None:
        await record_error(sm, categoria="NOTIFICACION", componente="notifications.outbox",
                           tipo="GENERATION_FAILED", severidad="ALTA",
                           descripcion=f"No se generó la notificación {plantilla}",
                           diagnostico={"plantilla": plantilla, "origen_id": origen_id})

    uow.after_commit.append(_record)


async def request_context(session: AsyncSession, solicitud_id: Any, actor: str | None
                          ) -> dict[str, Any]:
    row = (await session.execute(text(
        "SELECT s.numero, s.tipo, u.usuario_red FROM app.solicitud s LEFT JOIN app.usuario u "
        "ON s.entidad = 'usuario' AND u.id = s.entidad_id WHERE s.id = :i"),
        {"i": solicitud_id})).first()
    if row is None:
        return {}
    return {"numero": row[0], "tipo": row[1], "usuario_objetivo": row[2],
            "actor": actor or "Sistema"}
