"""Mantenimiento de sesiones (worker): cierra en BD las sesiones abandonadas.

Redis ya las invalida a los 15 min (REQ-AUTH-08); esto deja el registro histórico coherente
(`INACTIVIDAD`) aunque el usuario no vuelva a hacer ninguna petición ni a iniciar sesión.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.infrastructure import repository as repo
from app.modules.auth.infrastructure.session_store import SessionStore


async def close_abandoned_sessions(sm: async_sessionmaker[AsyncSession], store: SessionStore,
                                   spool: IncidentSpool, idle_seconds: int,
                                   limit: int = 200) -> int:
    async with sm() as s:
        rows = (await s.execute(text(
            "SELECT id, usuario_id FROM app.sesion WHERE finalizada_en IS NULL "
            "AND ultima_actividad < now() - make_interval(secs => :idle) LIMIT :l"),
            {"idle": idle_seconds + 60, "l": limit})).all()
    closed = 0
    for sid, uid in rows:
        if await store.is_active(uid, sid):
            continue  # hubo actividad reciente aún no persistida en BD
        async with UnitOfWork(sm, AuditContext.system(), spool) as uow:
            if not await repo.close_session(uow.session, sid, "INACTIVIDAD"):
                continue
            uow.audit(AuditEntry(categoria="AUTENTICACION", accion="AUTH_SESSION_EXPIRED",
                                 entidad="sesion", entidad_id=str(sid),
                                 detalle={"motivo": "INACTIVIDAD", "usuario_id": str(uid),
                                          "origen": "worker"}))
            await uow.commit()
            closed += 1
    return closed
