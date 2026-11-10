"""Unidad de trabajo con auditoría fail-closed (REQ-AUD-07, PD-04 APROBADO).

Uso:
    async with UnitOfWork(db.sessionmaker, ctx, spool) as uow:
        ...cambios con uow.session...
        uow.audit(AuditEntry(...))
        await uow.commit()

Garantías:
- Cambio de negocio y evento de auditoría se confirman en la MISMA transacción.
- Si el INSERT de auditoría falla: rollback total, incidente en el spool y AuditUnavailableError
  (HTTP 503). El cambio de negocio nunca queda persistido sin su evento.
- Un commit sin ningún evento de auditoría se rechaza (toda mutación debe auditarse).
"""

import logging
from types import TracebackType

from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AuditUnavailableError, ServiceUnavailableError
from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool, insert_audit

logger = logging.getLogger(__name__)


class MissingAuditError(RuntimeError):
    """Error de programación: se intentó confirmar una mutación sin auditarla."""


class UnitOfWork:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        ctx: AuditContext,
        spool: IncidentSpool,
    ) -> None:
        self._sessionmaker = sessionmaker
        self.ctx = ctx
        self._spool = spool
        self._pending: list[AuditEntry] = []
        self._committed = False
        self.session: AsyncSession

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self._sessionmaker()
        await self.session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if not self._committed:
                await self.session.rollback()
        finally:
            await self.session.close()

    def audit(self, entry: AuditEntry) -> None:
        self._pending.append(entry)

    async def commit(self) -> None:
        if not self._pending:
            raise MissingAuditError("toda mutación debe registrar al menos un evento de auditoría")

        # 1) Cambios de negocio: sus errores (p. ej. unicidad) se propagan tal cual.
        await self.session.flush()

        # 2) Auditoría en la misma transacción: si falla → fail-closed.
        try:
            for entry in self._pending:
                await insert_audit(self.session, entry, self.ctx)
        except (SQLAlchemyError, OSError) as exc:
            await self.session.rollback()
            logger.error("auditoría no disponible; operación bloqueada (%s)", type(exc).__name__)
            for entry in self._pending:
                self._spool.record(entry, self.ctx, type(exc).__name__)
            raise AuditUnavailableError() from exc

        # 3) Commit atómico.
        try:
            await self.session.commit()
        except DBAPIError as exc:
            await self.session.rollback()
            raise ServiceUnavailableError() from exc
        self._committed = True
