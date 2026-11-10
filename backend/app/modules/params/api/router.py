"""Parámetros generales (M §8.2). Operación directa (PD-05), auditada."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.errors import BusinessRuleError, NotFoundError
from app.kernel.audit import AuditEntry
from app.kernel.authz import require
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.api.dependencies import audit_context, get_auth_service
from app.modules.auth.application.service import AuthService, Principal

router = APIRouter(tags=["params"])
HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ParametroOut(BaseModel):
    clave: str
    valor: str | None
    tipo: str
    descripcion: str
    minimo: int | None
    maximo: int | None
    modificado_en: datetime | None


class ParametroIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    valor: str = Field(min_length=1, max_length=200)


@router.get("/admin/parameters", response_model=list[ParametroOut])
async def list_parameters(
    _: Principal = Depends(require("ADM.PARAMETRO.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[ParametroOut]:
    async with auth.sm() as s:
        rows = (await s.execute(text(
            "SELECT clave, valor, tipo, descripcion, minimo, maximo, modificado_en "
            "FROM ops.parametro ORDER BY clave"))).mappings().all()
    return [ParametroOut(**r) for r in rows]


@router.patch("/admin/parameters/{clave}", response_model=ParametroOut)
async def update_parameter(
    clave: str, body: ParametroIn, request: Request,
    p: Principal = Depends(require("ADM.PARAMETRO.EDICION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ParametroOut:
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        row = (await uow.session.execute(text(
            "SELECT * FROM ops.parametro WHERE clave = :c FOR UPDATE"),
            {"c": clave})).mappings().first()
        if row is None:
            raise NotFoundError()
        valor = body.valor
        if row["tipo"] == "ENTERO":
            if not valor.isdigit() or not (
                (row["minimo"] is None or int(valor) >= row["minimo"])
                and (row["maximo"] is None or int(valor) <= row["maximo"])
            ):
                raise BusinessRuleError(
                    f"Debe ser un entero entre {row['minimo']} y {row['maximo']}.")
        elif row["tipo"] == "HORA" and not HORA_RE.match(valor):
            raise BusinessRuleError("Debe tener formato HH:MM (24 h).")
        if valor == row["valor"]:
            raise BusinessRuleError("No hay cambios que aplicar.")
        new = (await uow.session.execute(text(
            "UPDATE ops.parametro SET valor = :v, modificado_en = now(), modificado_por = :u "
            "WHERE clave = :c RETURNING clave, valor, tipo, descripcion, minimo, maximo, "
            "modificado_en"), {"v": valor, "u": p.user_id, "c": clave})).mappings().one()
        uow.audit(AuditEntry(categoria="ADMINISTRACION", accion="PAR_UPDATED", modulo="ADM",
                             entidad="parametro", entidad_id=clave,
                             valor_anterior={"valor": row["valor"]}, valor_nuevo={"valor": valor}))
        await uow.commit()
    return ParametroOut(**new)
