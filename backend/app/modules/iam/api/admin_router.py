"""Operaciones IAM DIRECTAS (PD-05 APROBADO): perfiles, roles, permisos, módulos y dominios.

Todas: guarda `require(...)`, UnitOfWork con auditoría antes/después (fail-closed), sin
borrado físico. Cambios en roles/permisos exigen impacto previo confirmado (REQ-IAM-09).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.kernel.audit import AuditEntry
from app.kernel.authz import PERMISSION_RE, require
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.api.dependencies import audit_context, get_auth_service
from app.modules.auth.application.service import AuthService, Principal
from app.modules.iam.application import impact as imp
from app.modules.iam.application.associations import set_active

router = APIRouter(tags=["iam-admin"])

CODE = r"^[A-Z][A-Z0-9_]{1,39}$"
Estado = Literal["ACTIVO", "INACTIVO"]
CAT = "IAM"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CatalogCreate(_In):
    codigo: str = Field(pattern=CODE)
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str | None = Field(None, max_length=1000)


class CatalogPatch(_In):
    nombre: str | None = Field(None, min_length=1, max_length=100)
    descripcion: str | None = Field(None, max_length=1000)


class StatusIn(_In):
    estado: Estado
    confirm_impact_token: str | None = None


class CodesIn(_In):
    codigos: list[str] = Field(max_length=500)
    confirm_impact_token: str | None = None


class ImpactOut(BaseModel):
    perfiles_afectados: list[str]
    usuarios_afectados: int
    usuarios: list[str]
    agregados: list[str] = []
    quitados: list[str] = []
    confirm_impact_token: str


# ---------------------------------------------------------------------------- utilidades

@asynccontextmanager
async def _uow(request: Request, p: Principal, auth: AuthService) -> AsyncIterator[UnitOfWork]:
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        yield uow


async def _row(s: AsyncSession, table: str, oid: uuid.UUID, lock: bool = True) -> dict[str, Any]:
    row = (await s.execute(text(
        f"SELECT * FROM app.{table} WHERE id = :i{' FOR UPDATE' if lock else ''}"),  # noqa: S608
        {"i": oid})).mappings().first()
    if row is None:
        raise NotFoundError()
    return dict(row)


def _public(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: row[k] for k in keys if k in row}


def _protect(row: dict[str, Any], what: str) -> None:
    if row.get("es_sistema"):
        raise ConflictError(f"{what} de sistema está protegido y no puede modificarse.",
                            details={"codigo": row["codigo"]})


async def _ids_by_code(s: AsyncSession, table: str, codes: list[str]) -> dict[str, uuid.UUID]:
    codes = sorted(set(codes))
    rows = (await s.execute(text(
        f"SELECT codigo, id, estado FROM app.{table} WHERE codigo = ANY(:c)"),  # noqa: S608
        {"c": codes})).all()
    found = {r[0]: r for r in rows}
    missing = [c for c in codes if c not in found]
    inactive = [c for c in codes if c in found and found[c][2] != "ACTIVO"]
    if missing or inactive:
        raise BusinessRuleError("Hay códigos inexistentes o inactivos.",
                                details={"inexistentes": missing, "inactivos": inactive})
    return {c: found[c][1] for c in codes}


async def _insert(uow: UnitOfWork, table: str, cols: dict[str, Any], what: str) -> dict:
    names = ", ".join(cols)
    marks = ", ".join(f":{k}" for k in cols)
    try:
        async with uow.session.begin_nested():
            row = (await uow.session.execute(text(
                f"INSERT INTO app.{table} ({names}) VALUES ({marks}) RETURNING *"),  # noqa: S608
                cols)).mappings().one()
    except IntegrityError as exc:
        raise ConflictError(f"Ya existe {what} con ese código.") from exc
    return dict(row)


async def _patch(uow: UnitOfWork, table: str, row: dict, changes: dict[str, Any]) -> dict:
    changes = {k: v for k, v in changes.items() if v is not None and v != row.get(k)}
    if not changes:
        raise BusinessRuleError("No hay cambios que aplicar.")
    sets = ", ".join(f"{k} = :{k}" for k in changes)
    new = (await uow.session.execute(text(
        f"UPDATE app.{table} SET {sets}, modificado_en = now() WHERE id = :id "  # noqa: S608
        f"RETURNING *"), {**changes, "id": row["id"]})).mappings().one()
    return dict(new)


async def _set_status(uow: UnitOfWork, table: str, row: dict, estado: str) -> dict:
    if row["estado"] == estado:
        raise BusinessRuleError(f"El registro ya está {estado}.")
    new = (await uow.session.execute(text(
        f"UPDATE app.{table} SET estado = CAST(:e AS text), modificado_en = now(), "  # noqa: S608
        f"inhabilitado_en = CASE WHEN CAST(:e AS text) = 'INACTIVO' THEN now() ELSE NULL END "
        f"WHERE id = :id RETURNING *"), {"e": estado, "id": row["id"]})).mappings().one()
    return dict(new)


def _audit(uow: UnitOfWork, accion: str, entidad: str, row: dict, before: Any, after: Any,
           **detalle: Any) -> None:
    uow.audit(AuditEntry(categoria=CAT, accion=accion, modulo="ADM", entidad=entidad,
                         entidad_id=str(row["id"]), valor_anterior=before, valor_nuevo=after,
                         detalle=detalle or None))


FIELDS = ("codigo", "nombre", "descripcion", "estado")


def _secret(auth: AuthService) -> str:
    return auth.settings.jwt_secret.get_secret_value()


# ---------------------------------------------------------------------------- perfiles

@router.post("/admin/profiles", status_code=201)
async def create_profile(body: CatalogCreate, request: Request,
                         p: Principal = Depends(require("ADM.PERFIL.CREACION")),  # noqa: B008
                         auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _insert(uow, "perfil", body.model_dump(), "un perfil")
        _audit(uow, "IAM_PROFILE_CREATED", "perfil", row, None, _public(row, *FIELDS))
        await uow.commit()
    return _public(row, "id", *FIELDS)


@router.patch("/admin/profiles/{oid}")
async def patch_profile(oid: uuid.UUID, body: CatalogPatch, request: Request,
                        p: Principal = Depends(require("ADM.PERFIL.EDICION")),  # noqa: B008
                        auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "perfil", oid)
        _protect(row, "El perfil")
        new = await _patch(uow, "perfil", row, body.model_dump())
        _audit(uow, "IAM_PROFILE_UPDATED", "perfil", row, _public(row, *FIELDS),
               _public(new, *FIELDS))
        await uow.commit()
    return _public(new, "id", *FIELDS)


@router.post("/admin/profiles/{oid}/roles/impact", response_model=ImpactOut)
async def profile_roles_impact(oid: uuid.UUID, body: CodesIn,
                               _: Principal = Depends(require("ADM.PERFIL.EDICION")),  # noqa: B008
                               auth: AuthService = Depends(get_auth_service)) -> ImpactOut:  # noqa: B008
    async with auth.sm() as s:
        row = await _row(s, "perfil", oid, lock=False)
        _protect(row, "El perfil")
        await _ids_by_code(s, "rol", body.codigos)
        current = set((await s.execute(text(
            "SELECT r.codigo FROM app.perfil_rol pr JOIN app.rol r ON r.id = pr.rol_id "
            "WHERE pr.perfil_id = :p AND pr.estado = 'ACTIVO'"), {"p": oid})).scalars())
        impact = await imp.impact_of_profile(s, oid)
    change = sorted(set(body.codigos))
    return ImpactOut(**impact.as_dict(), agregados=sorted(set(change) - current),
                     quitados=sorted(current - set(change)),
                     confirm_impact_token=imp.issue_token(_secret(auth), "profile.roles", oid,
                                                          change, impact))


@router.put("/admin/profiles/{oid}/roles")
async def set_profile_roles(oid: uuid.UUID, body: CodesIn, request: Request,
                            p: Principal = Depends(require("ADM.PERFIL.EDICION")),  # noqa: B008
                            auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    change = sorted(set(body.codigos))
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "perfil", oid)
        _protect(row, "El perfil")
        ids = await _ids_by_code(uow.session, "rol", change)
        impact = await imp.impact_of_profile(uow.session, oid)
        imp.verify_token(_secret(auth), body.confirm_impact_token, "profile.roles", oid, change,
                         impact)
        before, after = await set_active(uow.session, "perfil_rol", oid, ids, p.user_id)
        _audit(uow, "IAM_PROFILE_ROLES", "perfil", row, {"roles": before}, {"roles": after},
               usuarios_afectados=len(impact.usuarios))
        await uow.commit()
    return {"id": oid, "roles": after}


@router.post("/admin/profiles/{oid}/status")
async def profile_status(oid: uuid.UUID, body: StatusIn, request: Request,
                         p: Principal = Depends(require("ADM.PERFIL.ELIMINACION")),  # noqa: B008
                         auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "perfil", oid)
        _protect(row, "El perfil")
        if body.estado == "INACTIVO":
            users = (await uow.session.execute(text(
                "SELECT usuario_red FROM app.usuario WHERE perfil_id = :p AND estado = 'ACTIVO' "
                "ORDER BY 1"), {"p": oid})).scalars().all()
            if users:  # REQ-IAM-08
                raise ConflictError(
                    "No se puede inactivar un perfil con usuarios activos; reasígnelos antes.",
                    details={"usuarios_activos": list(users)})
        new = await _set_status(uow, "perfil", row, body.estado)
        _audit(uow, "IAM_PROFILE_STATUS", "perfil", row, {"estado": row["estado"]},
               {"estado": new["estado"]})
        await uow.commit()
    return _public(new, "id", *FIELDS)


# ---------------------------------------------------------------------------- roles

@router.post("/admin/roles", status_code=201)
async def create_role(body: CatalogCreate, request: Request,
                      p: Principal = Depends(require("ADM.ROL.CREACION")),  # noqa: B008
                      auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _insert(uow, "rol", body.model_dump(), "un rol")
        _audit(uow, "IAM_ROLE_CREATED", "rol", row, None, _public(row, *FIELDS))
        await uow.commit()
    return _public(row, "id", *FIELDS)


@router.patch("/admin/roles/{oid}")
async def patch_role(oid: uuid.UUID, body: CatalogPatch, request: Request,
                     p: Principal = Depends(require("ADM.ROL.EDICION")),  # noqa: B008
                     auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "rol", oid)
        _protect(row, "El rol")
        new = await _patch(uow, "rol", row, body.model_dump())
        _audit(uow, "IAM_ROLE_UPDATED", "rol", row, _public(row, *FIELDS), _public(new, *FIELDS))
        await uow.commit()
    return _public(new, "id", *FIELDS)


@router.post("/admin/roles/{oid}/permissions/impact", response_model=ImpactOut)
async def role_permissions_impact(oid: uuid.UUID, body: CodesIn,
                                  _: Principal = Depends(require("ADM.ROL.EDICION")),  # noqa: B008
                                  auth: AuthService = Depends(get_auth_service)) -> ImpactOut:  # noqa: B008
    change = sorted(set(body.codigos))
    async with auth.sm() as s:
        row = await _row(s, "rol", oid, lock=False)
        _protect(row, "El rol")
        await _ids_by_code(s, "permiso", change)
        current = set((await s.execute(text(
            "SELECT p.codigo FROM app.rol_permiso rp JOIN app.permiso p ON p.id = rp.permiso_id "
            "WHERE rp.rol_id = :r AND rp.estado = 'ACTIVO'"), {"r": oid})).scalars())
        impact = await imp.impact_of_role(s, oid)
    return ImpactOut(**impact.as_dict(), agregados=sorted(set(change) - current),
                     quitados=sorted(current - set(change)),
                     confirm_impact_token=imp.issue_token(_secret(auth), "role.permissions", oid,
                                                          change, impact))


@router.put("/admin/roles/{oid}/permissions")
async def set_role_permissions(oid: uuid.UUID, body: CodesIn, request: Request,
                               p: Principal = Depends(require("ADM.ROL.EDICION")),  # noqa: B008
                               auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    change = sorted(set(body.codigos))
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "rol", oid)
        _protect(row, "El rol")
        ids = await _ids_by_code(uow.session, "permiso", change)
        impact = await imp.impact_of_role(uow.session, oid)
        imp.verify_token(_secret(auth), body.confirm_impact_token, "role.permissions", oid,
                         change, impact)
        before, after = await set_active(uow.session, "rol_permiso", oid, ids, p.user_id)
        _audit(uow, "IAM_ROLE_PERMISSIONS", "rol", row, {"permisos": before},
               {"permisos": after}, perfiles_afectados=impact.perfiles,
               usuarios_afectados=len(impact.usuarios))
        await uow.commit()
    return {"id": oid, "permisos": after}


@router.post("/admin/roles/{oid}/status/impact", response_model=ImpactOut)
async def role_status_impact(oid: uuid.UUID, body: StatusIn,
                             _: Principal = Depends(require("ADM.ROL.ELIMINACION")),  # noqa: B008
                             auth: AuthService = Depends(get_auth_service)) -> ImpactOut:  # noqa: B008
    async with auth.sm() as s:
        row = await _row(s, "rol", oid, lock=False)
        _protect(row, "El rol")
        impact = await imp.impact_of_role(s, oid)
    return ImpactOut(**impact.as_dict(), confirm_impact_token=imp.issue_token(
        _secret(auth), "role.status", oid, body.estado, impact))


@router.post("/admin/roles/{oid}/status")
async def role_status(oid: uuid.UUID, body: StatusIn, request: Request,
                      p: Principal = Depends(require("ADM.ROL.ELIMINACION")),  # noqa: B008
                      auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "rol", oid)
        _protect(row, "El rol")
        impact = await imp.impact_of_role(uow.session, oid)
        imp.verify_token(_secret(auth), body.confirm_impact_token, "role.status", oid,
                         body.estado, impact)
        new = await _set_status(uow, "rol", row, body.estado)
        _audit(uow, "IAM_ROLE_STATUS", "rol", row, {"estado": row["estado"]},
               {"estado": new["estado"]}, usuarios_afectados=len(impact.usuarios))
        await uow.commit()
    return _public(new, "id", *FIELDS)


# ---------------------------------------------------------------------------- permisos

class PermisoCreate(_In):
    codigo: str = Field(max_length=80)
    nombre: str = Field(min_length=1, max_length=150)
    descripcion: str | None = Field(None, max_length=1000)


@router.post("/admin/permissions", status_code=201)
async def create_permission(body: PermisoCreate, request: Request,
                            p: Principal = Depends(require("ADM.PERMISO.CREACION")),  # noqa: B008
                            auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    m = PERMISSION_RE.match(body.codigo)
    if not m:
        raise BusinessRuleError("Código inválido: use MÓDULO.RECURSO.CATEGORÍA "
                                "(categoría: CONSULTA, CREACION, EDICION, ELIMINACION, "
                                "APROBACION o EXPORTACION).")
    async with _uow(request, p, auth) as uow:
        modulo_id = (await uow.session.execute(text(
            "SELECT id FROM app.modulo WHERE codigo = :c"), {"c": m.group(1)})).scalar()
        if modulo_id is None:  # REQ-IAM-06: el permiso pertenece obligatoriamente a un módulo
            raise BusinessRuleError("El módulo del permiso no existe.")
        row = await _insert(uow, "permiso", {
            **body.model_dump(), "categoria": m.group(2), "modulo_id": modulo_id}, "un permiso")
        _audit(uow, "IAM_PERMISSION_CREATED", "permiso", row, None,
               {**_public(row, *FIELDS, "categoria"), "modulo": m.group(1)})
        await uow.commit()
    return _public(row, "id", *FIELDS, "categoria")


@router.patch("/admin/permissions/{oid}")
async def patch_permission(oid: uuid.UUID, body: CatalogPatch, request: Request,
                           p: Principal = Depends(require("ADM.PERMISO.EDICION")),  # noqa: B008
                           auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    # ESP-ADM-IAM R12: los permisos de sistema solo se describen (nombre/descripción).
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "permiso", oid)
        new = await _patch(uow, "permiso", row, body.model_dump())
        _audit(uow, "IAM_PERMISSION_UPDATED", "permiso", row, _public(row, *FIELDS),
               _public(new, *FIELDS))
        await uow.commit()
    return _public(new, "id", *FIELDS)


@router.post("/admin/permissions/{oid}/status/impact", response_model=ImpactOut)
async def permission_status_impact(oid: uuid.UUID, body: StatusIn,
                                   _: Principal = Depends(require("ADM.PERMISO.ELIMINACION")),  # noqa: B008
                                   auth: AuthService = Depends(get_auth_service)) -> ImpactOut:  # noqa: B008
    async with auth.sm() as s:
        row = await _row(s, "permiso", oid, lock=False)
        _protect(row, "El permiso")
        impact = await imp.impact_of_permission(s, oid)
    return ImpactOut(**impact.as_dict(), confirm_impact_token=imp.issue_token(
        _secret(auth), "permission.status", oid, body.estado, impact))


@router.post("/admin/permissions/{oid}/status")
async def permission_status(oid: uuid.UUID, body: StatusIn, request: Request,
                            p: Principal = Depends(require("ADM.PERMISO.ELIMINACION")),  # noqa: B008
                            auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "permiso", oid)
        _protect(row, "El permiso")
        impact = await imp.impact_of_permission(uow.session, oid)
        imp.verify_token(_secret(auth), body.confirm_impact_token, "permission.status", oid,
                         body.estado, impact)
        new = await _set_status(uow, "permiso", row, body.estado)
        _audit(uow, "IAM_PERMISSION_STATUS", "permiso", row, {"estado": row["estado"]},
               {"estado": new["estado"]}, usuarios_afectados=len(impact.usuarios))
        await uow.commit()
    return _public(new, "id", *FIELDS)


# ---------------------------------------------------------------------------- módulos

class ModuloCreate(_In):
    codigo: str = Field(pattern=r"^[A-Z]{2,16}$")
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str | None = Field(None, max_length=1000)
    ruta_frontend: str = Field(pattern=r"^/[a-z0-9\-/]{1,99}$")


class ModuloPatch(CatalogPatch):
    ruta_frontend: str | None = Field(None, pattern=r"^/[a-z0-9\-/]{1,99}$")


MOD_FIELDS = (*FIELDS, "orden", "ruta_frontend")


@router.post("/admin/modules", status_code=201)
async def create_module(body: ModuloCreate, request: Request,
                        p: Principal = Depends(require("ADM.MODULO.CREACION")),  # noqa: B008
                        auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        orden = (await uow.session.execute(text(
            "SELECT coalesce(max(orden), 0) + 1 FROM app.modulo"))).scalar_one()
        row = await _insert(uow, "modulo", {**body.model_dump(), "orden": orden}, "un módulo")
        _audit(uow, "IAM_MODULE_CREATED", "modulo", row, None, _public(row, *MOD_FIELDS))
        await uow.commit()
    return _public(row, "id", *MOD_FIELDS)


@router.patch("/admin/modules/{oid}")
async def patch_module(oid: uuid.UUID, body: ModuloPatch, request: Request,
                       p: Principal = Depends(require("ADM.MODULO.EDICION")),  # noqa: B008
                       auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "modulo", oid)
        new = await _patch(uow, "modulo", row, body.model_dump())
        _audit(uow, "IAM_MODULE_UPDATED", "modulo", row, _public(row, *MOD_FIELDS),
               _public(new, *MOD_FIELDS))
        await uow.commit()
    return _public(new, "id", *MOD_FIELDS)


@router.post("/admin/modules/{oid}/status")
async def module_status(oid: uuid.UUID, body: StatusIn, request: Request,
                        p: Principal = Depends(require("ADM.MODULO.ELIMINACION")),  # noqa: B008
                        auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    """REQ-IAM-11: inactivar revoca el acceso (la guarda lo verifica en cada petición).
    Reactivar devuelve las asignaciones históricas para revisión (se mantienen como estaban)."""
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "modulo", oid)
        if row["codigo"] == "ADM" and body.estado == "INACTIVO":
            raise ConflictError("El módulo de Administración no puede inactivarse.")
        new = await _set_status(uow, "modulo", row, body.estado)
        asignaciones = (await uow.session.execute(text(
            "SELECT u.usuario_red, um.estado AS asignacion, u.estado AS usuario "
            "FROM app.usuario_modulo um JOIN app.usuario u ON u.id = um.usuario_id "
            "WHERE um.modulo_id = :m ORDER BY 1"), {"m": oid})).mappings().all()
        _audit(uow, "IAM_MODULE_STATUS", "modulo", row, {"estado": row["estado"]},
               {"estado": new["estado"]}, asignaciones=len(asignaciones))
        await uow.commit()
    return {**_public(new, "id", *MOD_FIELDS),
            "asignaciones_a_revisar": [dict(a) for a in asignaciones]
            if body.estado == "ACTIVO" else []}


class OrderIn(_In):
    codigos: list[str] = Field(min_length=1, max_length=100)


@router.put("/admin/modules/order")
async def order_modules(body: OrderIn, request: Request,
                        p: Principal = Depends(require("ADM.MODULO.EDICION")),  # noqa: B008
                        auth: AuthService = Depends(get_auth_service)) -> list[str]:  # noqa: B008
    """REQ-IAM-13: orden uniforme; operación directa (APROBADO) y auditada."""
    async with _uow(request, p, auth) as uow:
        s = uow.session
        before = list((await s.execute(text(
            "SELECT codigo FROM app.modulo ORDER BY orden FOR UPDATE"))).scalars())
        if sorted(before) != sorted(body.codigos) or len(set(body.codigos)) != len(body.codigos):
            raise BusinessRuleError("Debe enviar todos los módulos exactamente una vez.",
                                    details={"modulos": before})
        if before == body.codigos:
            raise BusinessRuleError("No hay cambios que aplicar.")
        await s.execute(text("SET CONSTRAINTS app.modulo_orden_key DEFERRED"))
        for i, code in enumerate(body.codigos, start=1):
            await s.execute(text("UPDATE app.modulo SET orden = :o, modificado_en = now() "
                                 "WHERE codigo = :c"), {"o": i, "c": code})
        uow.audit(AuditEntry(categoria=CAT, accion="IAM_MODULE_ORDER", modulo="ADM",
                             entidad="modulo", valor_anterior={"orden": before},
                             valor_nuevo={"orden": body.codigos}))
        await uow.commit()
    return body.codigos


# ---------------------------------------------------------------------------- dominios

class DominioCreate(CatalogCreate):
    nombre: str = Field(min_length=1, max_length=150)
    modulo: str | None = Field(None, pattern=r"^[A-Z]{2,16}$")


@router.post("/admin/domains", status_code=201)
async def create_domain(body: DominioCreate, request: Request,
                        p: Principal = Depends(require("ADM.DOMINIO.CREACION")),  # noqa: B008
                        auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        modulo_id = None
        if body.modulo:
            modulo_id = (await _ids_by_code(uow.session, "modulo", [body.modulo]))[body.modulo]
        data = body.model_dump(exclude={"modulo"}) | {"modulo_id": modulo_id}
        row = await _insert(uow, "dominio", data, "un dominio")
        _audit(uow, "IAM_DOMAIN_CREATED", "dominio", row, None,
               {**_public(row, *FIELDS), "modulo": body.modulo})
        await uow.commit()
    return _public(row, "id", *FIELDS)


@router.patch("/admin/domains/{oid}")
async def patch_domain(oid: uuid.UUID, body: CatalogPatch, request: Request,
                       p: Principal = Depends(require("ADM.DOMINIO.EDICION")),  # noqa: B008
                       auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "dominio", oid)
        new = await _patch(uow, "dominio", row, body.model_dump())
        _audit(uow, "IAM_DOMAIN_UPDATED", "dominio", row, _public(row, *FIELDS),
               _public(new, *FIELDS))
        await uow.commit()
    return _public(new, "id", *FIELDS)


@router.post("/admin/domains/{oid}/status")
async def domain_status(oid: uuid.UUID, body: StatusIn, request: Request,
                        p: Principal = Depends(require("ADM.DOMINIO.ELIMINACION")),  # noqa: B008
                        auth: AuthService = Depends(get_auth_service)) -> dict:  # noqa: B008
    async with _uow(request, p, auth) as uow:
        row = await _row(uow.session, "dominio", oid)
        new = await _set_status(uow, "dominio", row, body.estado)
        _audit(uow, "IAM_DOMAIN_STATUS", "dominio", row, {"estado": row["estado"]},
               {"estado": new["estado"]})
        await uow.commit()
    return _public(new, "id", *FIELDS)
