"""Registro centralizado de errores (CU-ERR-01; REQ-ERR-01/02). Sin borrado."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.core.errors import BusinessRuleError, NotFoundError
from app.kernel.audit import AuditEntry
from app.kernel.authz import require
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.api.dependencies import audit_context, get_auth_service
from app.modules.auth.application.service import AuthService, Principal

router = APIRouter(tags=["errors"])
EstadoAtencion = Literal["ABIERTO", "EN_ATENCION", "CERRADO"]


class ErrorOut(BaseModel):
    id: uuid.UUID
    ocurrido_en: datetime
    categoria: str
    modulo: str | None
    componente: str
    tipo: str
    severidad: str
    descripcion: str
    diagnostico: Any
    estado_atencion: str
    correlation_id: str | None
    atendido_en: datetime | None


class ErroresPage(BaseModel):
    items: list[ErrorOut]
    total: int


@router.get("/admin/errors", response_model=ErroresPage)
async def list_errors(
    categoria: str | None = Query(None, max_length=32),
    severidad: Literal["BAJA", "MEDIA", "ALTA", "CRITICA"] | None = None,
    estado: EstadoAtencion | None = None,
    correlation_id: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: Principal = Depends(require("ADM.ERROR.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ErroresPage:
    where = """ WHERE (CAST(:c AS text) IS NULL OR categoria = :c)
                  AND (CAST(:s AS text) IS NULL OR severidad = :s)
                  AND (CAST(:e AS text) IS NULL OR estado_atencion = :e)
                  AND (CAST(:r AS text) IS NULL OR correlation_id = :r) """
    params = {"c": categoria, "s": severidad, "e": estado, "r": correlation_id}
    async with auth.sm() as s:
        total = (await s.execute(text(f"SELECT count(*) FROM ops.registro_error {where}"),  # noqa: S608
                                 params)).scalar_one()
        cols = ("id, ocurrido_en, categoria, modulo, componente, tipo, severidad, descripcion, "
                "diagnostico, estado_atencion, correlation_id, atendido_en")
        # `where` es un texto fijo con parámetros enlazados (sin entrada del usuario).
        query = f"SELECT {cols} FROM ops.registro_error {where} "  # noqa: S608
        query += "ORDER BY ocurrido_en DESC LIMIT :l OFFSET :o"
        rows = (await s.execute(text(query),
            {**params, "l": page_size, "o": (page - 1) * page_size})).mappings().all()
    return ErroresPage(items=[ErrorOut(**r) for r in rows], total=total)


class AtencionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estado_atencion: EstadoAtencion


@router.patch("/admin/errors/{error_id}", response_model=ErrorOut)
async def update_error(
    error_id: uuid.UUID, body: AtencionIn, request: Request,
    p: Principal = Depends(require("ADM.ERROR.EDICION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ErrorOut:
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        row = (await uow.session.execute(text(
            "SELECT estado_atencion FROM ops.registro_error WHERE id = :i FOR UPDATE"),
            {"i": error_id})).first()
        if row is None:
            raise NotFoundError()
        if row[0] == body.estado_atencion:
            raise BusinessRuleError("No hay cambios que aplicar.")
        new = (await uow.session.execute(text(
            "UPDATE ops.registro_error SET estado_atencion = :e, atendido_por = :u, "
            "atendido_en = now() WHERE id = :i RETURNING id, ocurrido_en, categoria, modulo, "
            "componente, tipo, severidad, descripcion, diagnostico, estado_atencion, "
            "correlation_id, atendido_en"),
            {"e": body.estado_atencion, "u": p.user_id, "i": error_id})).mappings().one()
        uow.audit(AuditEntry(categoria="ADMINISTRACION", accion="ERR_STATUS_CHANGED",
                             modulo="ADM", entidad="registro_error", entidad_id=str(error_id),
                             valor_anterior={"estado_atencion": row[0]},
                             valor_nuevo={"estado_atencion": body.estado_atencion}))
        await uow.commit()
    return ErrorOut(**new)
