"""Consulta, exportación y verificación de la auditoría (CU-AUD-01..03; REQ-AUD-04/06).

Toda consulta/exportación/verificación de auditoría se audita (M §11.4), fail-closed.
No existen endpoints de edición ni borrado: la BD garantiza la inmutabilidad.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.excel import MAX_EXPORT_ROWS, build_xlsx, xlsx_response
from app.kernel.audit import AuditEntry
from app.kernel.authz import require
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.api.dependencies import audit_context, get_auth_service
from app.modules.auth.application.service import AuthService, Principal

router = APIRouter(tags=["audit"])

COLUMNS = ("seq", "id", "ocurrido_en", "actor_usuario_red", "actor_tipo", "categoria", "modulo",
           "accion", "entidad", "entidad_id", "resultado", "motivo", "ip_origen",
           "correlation_id", "solicitud_id", "valor_anterior", "valor_nuevo", "detalle")


class AuditFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    desde: datetime | None = None
    hasta: datetime | None = None
    actor: str | None = Field(None, max_length=16, description="Usuario de red del actor")
    categoria: str | None = Field(None, max_length=32)
    accion: str | None = Field(None, max_length=64)
    modulo: str | None = Field(None, max_length=16)
    entidad: str | None = Field(None, max_length=64)
    entidad_id: str | None = Field(None, max_length=64)
    resultado: Literal["EXITO", "FALLO", "DENEGADO"] | None = None
    correlation_id: str | None = Field(None, max_length=64)


_WHERE = """
 WHERE (CAST(:desde AS timestamptz) IS NULL OR e.ocurrido_en >= :desde)
   AND (CAST(:hasta AS timestamptz) IS NULL OR e.ocurrido_en < :hasta)
   AND (CAST(:actor AS text) IS NULL OR e.actor_usuario_red = lower(:actor))
   AND (CAST(:categoria AS text) IS NULL OR e.categoria = :categoria)
   AND (CAST(:accion AS text) IS NULL OR e.accion = :accion)
   AND (CAST(:modulo AS text) IS NULL OR e.modulo = :modulo)
   AND (CAST(:entidad AS text) IS NULL OR e.entidad = :entidad)
   AND (CAST(:entidad_id AS text) IS NULL OR e.entidad_id = :entidad_id)
   AND (CAST(:resultado AS text) IS NULL OR e.resultado = :resultado)
   AND (CAST(:correlation_id AS text) IS NULL OR e.correlation_id = :correlation_id)
"""
_SELECT = ("SELECT e.seq, e.id, e.ocurrido_en, e.actor_usuario_red, e.actor_tipo, e.categoria, "
           "e.modulo, e.accion, e.entidad, e.entidad_id, e.resultado, e.motivo, "
           "host(e.ip_origen) AS ip_origen, e.correlation_id, e.solicitud_id, e.valor_anterior, "
           "e.valor_nuevo, e.detalle FROM audit.evento e")


class EventoOut(BaseModel):
    seq: int
    id: uuid.UUID
    ocurrido_en: datetime
    actor_usuario_red: str | None
    actor_tipo: str
    categoria: str
    modulo: str | None
    accion: str
    entidad: str | None
    entidad_id: str | None
    resultado: str
    motivo: str | None
    ip_origen: str | None
    correlation_id: str | None
    solicitud_id: uuid.UUID | None
    valor_anterior: Any
    valor_nuevo: Any
    detalle: Any


class EventosPage(BaseModel):
    items: list[EventoOut]
    total: int


async def _audit(auth: AuthService, request: Request, p: Principal, accion: str,
                 detalle: dict[str, Any]) -> None:
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        uow.audit(AuditEntry(categoria="AUDITORIA", accion=accion, modulo="ADM",
                             detalle=detalle))
        await uow.commit()


def _filters_dict(f: AuditFilter) -> dict[str, Any]:
    return {k: v for k, v in f.model_dump(mode="json").items() if v is not None}


@router.get("/admin/audit/events", response_model=EventosPage)
async def query_events(
    request: Request,
    f: AuditFilter = Depends(),  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    p: Principal = Depends(require("ADM.AUDITORIA.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> EventosPage:
    params = f.model_dump()
    # La consulta se audita ANTES de devolver datos (fail-closed).
    await _audit(auth, request, p, "AUD_QUERIED",
                 {"filtros": _filters_dict(f), "pagina": page})
    async with auth.sm() as s:
        total = (await s.execute(text(f"SELECT count(*) FROM audit.evento e {_WHERE}"),  # noqa: S608
                                 params)).scalar_one()
        rows = (await s.execute(text(
            f"{_SELECT} {_WHERE} ORDER BY e.seq DESC LIMIT :l OFFSET :o"),  # noqa: S608
            {**params, "l": page_size, "o": (page - 1) * page_size})).mappings().all()
    return EventosPage(items=[EventoOut(**r) for r in rows], total=total)


@router.post("/admin/audit/events/export")
async def export_events(
    f: AuditFilter, request: Request,
    p: Principal = Depends(require("ADM.AUDITORIA.EXPORTACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> Response:
    params = f.model_dump()
    async with auth.sm() as s:
        rows = (await s.execute(text(
            f"{_SELECT} {_WHERE} ORDER BY e.seq LIMIT :l"),  # noqa: S608
            {**params, "l": MAX_EXPORT_ROWS + 1})).all()
    truncated = len(rows) > MAX_EXPORT_ROWS
    rows = rows[:MAX_EXPORT_ROWS]
    await _audit(auth, request, p, "AUD_EXPORTED",
                 {"filtros": _filters_dict(f), "filas": len(rows), "truncado": truncated})
    content = build_xlsx("auditoria", COLUMNS, rows)
    return xlsx_response(content, "secureone-auditoria.xlsx", truncated)


class VerifyOut(BaseModel):
    integra: bool
    total_eventos: int
    primer_seq_invalido: int | None


@router.get("/admin/audit/verify", response_model=VerifyOut)
async def verify_chain(
    request: Request,
    p: Principal = Depends(require("ADM.AUDITORIA.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> VerifyOut:
    async with auth.sm() as s:
        row = (await s.execute(text("SELECT * FROM audit.verificar_cadena()"))).one()
    out = VerifyOut(integra=row.primer_seq_invalido is None, total_eventos=row.total,
                    primer_seq_invalido=row.primer_seq_invalido)
    await _audit(auth, request, p, "AUD_VERIFIED", out.model_dump())
    return out
