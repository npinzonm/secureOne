"""Solicitudes: consulta (CU-APR-01) y resolución (CU-APR-02..04, Fase 6)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.errors import NotFoundError
from app.kernel.authz import require
from app.kernel.unit_of_work import UnitOfWork
from app.modules.approvals.application import resolution
from app.modules.approvals.application.resolution import Resolution
from app.modules.auth.api.dependencies import audit_context, get_auth_service
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


# ============================================================================ resolución (Fase 6)

class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AprobarIn(_In):
    comentario: str | None = Field(None, max_length=1000)


class MotivoResolucionIn(_In):
    motivo: str = Field(min_length=10, max_length=1000)  # REQ-APR-05 (mínimo 10: PROPUESTO)


class ResolucionOut(BaseModel):
    solicitud_id: uuid.UUID
    numero: int
    tipo: str
    estado: str
    usuario_id: uuid.UUID
    contrasena_temporal: str | None = None
    mensaje: str | None = None


def _out(r: Resolution) -> ResolucionOut:
    msg = None
    if r.contrasena_temporal:
        msg = ("Contraseña temporal: se muestra una sola vez. Entréguela por un canal seguro; "
               "deberá cambiarse en el primer inicio de sesión.")
    return ResolucionOut(solicitud_id=r.solicitud_id, numero=r.numero, tipo=r.tipo,
                         estado=r.estado, usuario_id=r.usuario_id,
                         contrasena_temporal=r.contrasena_temporal, mensaje=msg)


@router.post("/admin/requests/{request_id}/approve", response_model=ResolucionOut)
async def approve_request(
    request_id: uuid.UUID, request: Request, response: Response,
    body: AprobarIn | None = None,
    p: Principal = Depends(require("ADM.SOLICITUD.APROBACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ResolucionOut:
    """CU-APR-02 / D-APR-001: una aprobación; cualquier administrador; autoaprobación permitida."""
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        r = await resolution.approve(uow, request_id, p.user_id, auth.settings, auth.store,
                                     body.comentario if body else None)
        await uow.commit()
    response.headers["Cache-Control"] = "no-store"
    return _out(r)


@router.post("/admin/requests/{request_id}/reject", response_model=ResolucionOut)
async def reject_request(
    request_id: uuid.UUID, body: MotivoResolucionIn, request: Request,
    p: Principal = Depends(require("ADM.SOLICITUD.APROBACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ResolucionOut:
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        r = await resolution.reject_or_cancel(uow, request_id, p.user_id, body.motivo,
                                              "RECHAZADA")
        await uow.commit()
    return _out(r)


@router.post("/admin/requests/{request_id}/cancel", response_model=ResolucionOut)
async def cancel_request(
    request_id: uuid.UUID, body: MotivoResolucionIn, request: Request,
    p: Principal = Depends(require("ADM.SOLICITUD.CREACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ResolucionOut:
    """CU-APR-04 / REQ-APR-06: para corregir, cancelar y crear otra solicitud vinculada."""
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        r = await resolution.reject_or_cancel(uow, request_id, p.user_id, body.motivo,
                                              "CANCELADA")
        await uow.commit()
    return _out(r)
