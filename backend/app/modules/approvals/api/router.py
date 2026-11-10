"""Consulta de solicitudes (CU-APR-01). Aprobar/rechazar/cancelar: Fase 6."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.core.errors import NotFoundError
from app.kernel.authz import require
from app.modules.auth.api.dependencies import get_auth_service
from app.modules.auth.application.service import AuthService, Principal

router = APIRouter(tags=["approvals"])

_SELECT = """
    SELECT s.id, s.numero, s.tipo, s.origen, s.entidad, s.entidad_id, s.estado, s.motivo,
           s.creada_en, s.resuelta_en, s.motivo_resolucion, s.solicitud_vinculada_id,
           us.usuario_red AS solicitante, ur.usuario_red AS resuelta_por,
           ut.usuario_red AS usuario_objetivo
      FROM app.solicitud s
      LEFT JOIN app.usuario us ON us.id = s.solicitante_id
      LEFT JOIN app.usuario ur ON ur.id = s.resuelta_por_id
      LEFT JOIN app.usuario ut ON s.entidad = 'usuario' AND ut.id = s.entidad_id
"""


class SolicitudOut(BaseModel):
    id: uuid.UUID
    numero: int
    tipo: str
    origen: str
    entidad: str
    entidad_id: uuid.UUID
    estado: str
    motivo: str | None
    creada_en: datetime
    resuelta_en: datetime | None
    motivo_resolucion: str | None
    solicitud_vinculada_id: uuid.UUID | None
    solicitante: str | None
    resuelta_por: str | None
    usuario_objetivo: str | None


class ItemOut(BaseModel):
    orden: int
    atributo: str
    valor_anterior: Any
    valor_nuevo: Any


class SolicitudDetalleOut(SolicitudOut):
    items: list[ItemOut]


class SolicitudesPage(BaseModel):
    items: list[SolicitudOut]
    total: int


@router.get("/admin/requests", response_model=SolicitudesPage)
async def list_requests(
    estado: Literal["PENDIENTE", "APROBADA", "RECHAZADA", "CANCELADA", "SUPERADA"] | None = None,
    tipo: str | None = Query(None, max_length=32),
    origen: Literal["MANUAL", "TH"] | None = None,
    entidad_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _: Principal = Depends(require("ADM.SOLICITUD.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> SolicitudesPage:
    where = """ WHERE (CAST(:e AS text) IS NULL OR s.estado = :e)
                  AND (CAST(:t AS text) IS NULL OR s.tipo = :t)
                  AND (CAST(:o AS text) IS NULL OR s.origen = :o)
                  AND (CAST(:i AS uuid) IS NULL OR s.entidad_id = :i) """
    params = {"e": estado, "t": tipo, "o": origen, "i": entidad_id}
    async with auth.sm() as s:
        total = (await s.execute(text(f"SELECT count(*) FROM app.solicitud s {where}"),  # noqa: S608
                                 params)).scalar_one()
        rows = (await s.execute(text(
            f"{_SELECT} {where} ORDER BY s.numero DESC LIMIT :l OFFSET :off"),  # noqa: S608
            {**params, "l": page_size, "off": (page - 1) * page_size})).mappings().all()
    return SolicitudesPage(items=[SolicitudOut(**r) for r in rows], total=total)


@router.get("/admin/requests/{request_id}", response_model=SolicitudDetalleOut)
async def get_request(
    request_id: uuid.UUID,
    _: Principal = Depends(require("ADM.SOLICITUD.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> SolicitudDetalleOut:
    async with auth.sm() as s:
        row = (await s.execute(text(f"{_SELECT} WHERE s.id = :id"),  # noqa: S608
                               {"id": request_id})).mappings().first()
        if row is None:
            raise NotFoundError()
        items = (await s.execute(text(
            "SELECT orden, atributo, valor_anterior, valor_nuevo FROM app.solicitud_item "
            "WHERE solicitud_id = :id ORDER BY orden"), {"id": request_id})).mappings().all()
    return SolicitudDetalleOut(**row, items=[ItemOut(**i) for i in items])
