"""Operaciones administrativas sobre usuarios según la matriz PD-05 (APROBADA).

Directas:   contraseña temporal, revocar sesión.
Con aprobación (solo crean la solicitud; se aplican en la Fase 6):
            alta, modificación agrupada (incluye perfil), módulos, inhabilitación, reactivación.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import uuid7
from app.kernel.audit import AuditEntry
from app.kernel.authz import require
from app.kernel.unit_of_work import UnitOfWork
from app.modules.approvals.application.requests import CreatedRequest, Item, create_request
from app.modules.auth.api.dependencies import audit_context, get_auth_service
from app.modules.auth.application.service import AuthService, Principal
from app.modules.auth.domain.password_policy import generate_temporary_password
from app.modules.auth.infrastructure import repository as auth_repo
from app.modules.auth.infrastructure.hashing import hash_password
from app.modules.users.domain.identifiers import (
    is_valid_email,
    is_valid_identificacion,
    is_valid_usuario_red,
    normalize_usuario_red,
)

router = APIRouter(tags=["users-admin"])

MOTIVO = Field(min_length=10, max_length=1000)  # PROPUESTO: motivo mínimo de 10 caracteres


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)  # rechaza `empresa`


class RequestOut(BaseModel):
    solicitud_id: uuid.UUID
    numero: int
    tipo: str
    estado: str
    usuario_id: uuid.UUID


@asynccontextmanager
async def _uow(request: Request, p: Principal, auth: AuthService) -> AsyncIterator[UnitOfWork]:
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        yield uow


def _out(r: CreatedRequest, uid: uuid.UUID) -> RequestOut:
    return RequestOut(solicitud_id=r.id, numero=r.numero, tipo=r.tipo, estado=r.estado,
                      usuario_id=uid)


async def _user(s: AsyncSession, uid: uuid.UUID) -> dict[str, Any]:
    row = (await s.execute(text(
        "SELECT u.*, pf.codigo AS perfil FROM app.usuario u JOIN app.perfil pf "
        "ON pf.id = u.perfil_id WHERE u.id = :u FOR UPDATE OF u"), {"u": uid})).mappings().first()
    if row is None:
        raise NotFoundError()
    return dict(row)


async def _active_id(s: AsyncSession, sql: str, value: Any, label: str) -> uuid.UUID:
    row = (await s.execute(text(sql), {"v": value})).first()
    if row is None:
        raise BusinessRuleError(f"{label} no existe.")
    if row[1] != "ACTIVO":
        raise BusinessRuleError(f"{label} está inactivo.")
    return row[0]


async def _validate_org(s: AsyncSession, g: uuid.UUID, a: uuid.UUID, c: uuid.UUID) -> None:
    await _active_id(s, "SELECT id, estado FROM app.gerencia WHERE id = :v", g, "La gerencia")
    await _active_id(s, "SELECT id, estado FROM app.cargo WHERE id = :v", c, "El cargo")
    area = (await s.execute(text("SELECT estado, gerencia_id FROM app.area WHERE id = :a"),
                            {"a": a})).first()
    if area is None or area[0] != "ACTIVO":
        raise BusinessRuleError("El área no existe o está inactiva.")
    if area[1] != g:  # REQ-USER-06
        raise BusinessRuleError("El área no pertenece a la gerencia seleccionada.")


async def _module_ids(s: AsyncSession, codes: list[str]) -> list[str]:
    codes = sorted(set(codes))
    rows = (await s.execute(text("SELECT codigo, estado FROM app.modulo WHERE codigo = ANY(:c)"),
                            {"c": codes})).all()
    found = {r[0]: r[1] for r in rows}
    bad = [c for c in codes if found.get(c) != "ACTIVO"]
    if bad:
        raise BusinessRuleError("Hay módulos inexistentes o inactivos.", details={"modulos": bad})
    return codes


async def _current_modules(s: AsyncSession, uid: uuid.UUID) -> list[str]:
    return list((await s.execute(text(
        "SELECT m.codigo FROM app.usuario_modulo um JOIN app.modulo m ON m.id = um.modulo_id "
        "WHERE um.usuario_id = :u AND um.estado = 'ACTIVO' ORDER BY 1"), {"u": uid})).scalars())


async def _active_admins(s: AsyncSession) -> int:
    return (await s.execute(text(
        "SELECT count(*) FROM app.usuario u JOIN app.perfil pf ON pf.id = u.perfil_id "
        "WHERE pf.codigo = 'ADMINISTRADOR' AND u.estado = 'ACTIVO'"))).scalar_one()


# ============================================================================ CON APROBACIÓN

class AltaIn(_In):
    usuario_red: str = Field(max_length=16)
    identificacion: str = Field(max_length=20)
    nombre: str = Field(min_length=1, max_length=100)
    primer_apellido: str = Field(min_length=1, max_length=50)
    segundo_apellido: str | None = Field(None, max_length=50)
    correo: str = Field(max_length=150)
    perfil: str = Field(max_length=40)
    gerencia_id: uuid.UUID
    area_id: uuid.UUID
    cargo_id: uuid.UUID
    tipo_alta: Literal["NORMAL", "EXCEPCIONAL"]
    modulos: list[str] = Field(default_factory=list, max_length=50)
    motivo: str | None = Field(None, max_length=1000)


@router.post("/admin/users", status_code=202, response_model=RequestOut)
async def request_user_creation(
    body: AltaIn, request: Request,
    p: Principal = Depends(require("ADM.USUARIO.CREACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> RequestOut:
    """CU-USR-03 / REQ-USER-01, 07: alta individual; efectiva solo al aprobarse (Fase 6)."""
    red = normalize_usuario_red(body.usuario_red)
    if not is_valid_usuario_red(red):
        raise BusinessRuleError("Usuario de red inválido: 8 caracteres alternados letra/número.")
    if not is_valid_identificacion(body.identificacion):
        raise BusinessRuleError("Identificación inválida.")
    if not is_valid_email(body.correo):
        raise BusinessRuleError("Correo inválido.")
    async with _uow(request, p, auth) as uow:
        s = uow.session
        dup = (await s.execute(text(
            "SELECT usuario_red = :r AS red, identificacion = :i AS ident FROM app.usuario "
            "WHERE usuario_red = :r OR identificacion = :i"),
            {"r": red, "i": body.identificacion})).mappings().all()
        if dup:  # REQ-USER-04: únicos (incluye inactivos y altas pendientes)
            raise ConflictError("El usuario de red o la identificación ya existen.", details={
                "usuario_red": any(d["red"] for d in dup),
                "identificacion": any(d["ident"] for d in dup)})
        perfil_id = await _active_id(s, "SELECT id, estado FROM app.perfil WHERE codigo = :v",
                                     body.perfil, "El perfil")
        await _validate_org(s, body.gerencia_id, body.area_id, body.cargo_id)
        modulos = await _module_ids(s, body.modulos)
        uid = uuid7()
        await s.execute(text(
            "INSERT INTO app.usuario (id, usuario_red, identificacion, nombre, primer_apellido, "
            "segundo_apellido, correo, perfil_id, gerencia_id, area_id, cargo_id, tipo_alta, "
            "estado, creado_por) VALUES (:id, :r, :i, :n, :a1, :a2, :c, :pf, :g, :ar, :cg, :t, "
            "'PENDIENTE_ALTA', :by)"),
            {"id": uid, "r": red, "i": body.identificacion, "n": body.nombre,
             "a1": body.primer_apellido, "a2": body.segundo_apellido or None, "c": body.correo,
             "pf": perfil_id, "g": body.gerencia_id, "ar": body.area_id, "cg": body.cargo_id,
             "t": body.tipo_alta, "by": p.user_id})
        nuevo = {"usuario_red": red, "identificacion": body.identificacion,
                 "nombre": body.nombre, "primer_apellido": body.primer_apellido,
                 "segundo_apellido": body.segundo_apellido or None, "correo": body.correo,
                 "perfil": body.perfil, "gerencia_id": str(body.gerencia_id),
                 "area_id": str(body.area_id), "cargo_id": str(body.cargo_id),
                 "tipo_alta": body.tipo_alta, "modulos": modulos, "estado": "ACTIVO"}
        created = await create_request(
            uow, tipo="ALTA_USUARIO", entidad="usuario", entidad_id=uid,
            solicitante_id=p.user_id, motivo=body.motivo,
            items=[Item(k, None, v) for k, v in nuevo.items()])
        await uow.commit()
    return _out(created, uid)


class ModificacionIn(_In):
    identificacion: str | None = Field(None, max_length=20)
    nombre: str | None = Field(None, min_length=1, max_length=100)
    primer_apellido: str | None = Field(None, min_length=1, max_length=50)
    segundo_apellido: str | None = Field(None, max_length=50)
    correo: str | None = Field(None, max_length=150)
    perfil: str | None = Field(None, max_length=40)
    gerencia_id: uuid.UUID | None = None
    area_id: uuid.UUID | None = None
    cargo_id: uuid.UUID | None = None
    motivo: str | None = Field(None, max_length=1000)


@router.patch("/admin/users/{user_id}", status_code=202, response_model=RequestOut)
async def request_user_update(
    user_id: uuid.UUID, body: ModificacionIn, request: Request,
    p: Principal = Depends(require("ADM.USUARIO.EDICION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> RequestOut:
    """CU-USR-04 / D-APR-002: cambios múltiples agrupados en UNA solicitud, un ítem por atributo."""
    async with _uow(request, p, auth) as uow:
        s = uow.session
        u = await _user(s, user_id)
        if u["estado"] != "ACTIVO":
            raise BusinessRuleError("Solo se modifican usuarios activos.")
        fields = body.model_dump(exclude={"motivo"}, exclude_unset=True)
        current = {k: (str(u[k]) if isinstance(u.get(k), uuid.UUID) else u.get(k))
                   for k in fields if k != "perfil"}
        current["perfil"] = u["perfil"]
        changes = {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in fields.items()
                   if (str(v) if isinstance(v, uuid.UUID) else v) != current.get(k)}
        if not changes:
            raise BusinessRuleError("No hay cambios respecto de los valores actuales.")
        if "identificacion" in changes:
            if not is_valid_identificacion(changes["identificacion"] or ""):
                raise BusinessRuleError("Identificación inválida.")
            if (await s.execute(text("SELECT 1 FROM app.usuario WHERE identificacion = :i "
                                     "AND id <> :u"),
                                {"i": changes["identificacion"], "u": user_id})).first():
                raise ConflictError("La identificación ya existe.")
        if "correo" in changes and not is_valid_email(changes["correo"] or ""):
            raise BusinessRuleError("Correo inválido.")
        if "perfil" in changes:
            await _active_id(s, "SELECT id, estado FROM app.perfil WHERE codigo = :v",
                             changes["perfil"], "El perfil")
        if {"gerencia_id", "area_id", "cargo_id"} & changes.keys():
            g = changes.get("gerencia_id", u["gerencia_id"])
            a = changes.get("area_id", u["area_id"])
            c = changes.get("cargo_id", u["cargo_id"])
            if not (g and a and c):
                raise BusinessRuleError("Gerencia, área y cargo son obligatorios.")
            await _validate_org(s, uuid.UUID(str(g)), uuid.UUID(str(a)), uuid.UUID(str(c)))
        if u["perfil"] == "ADMINISTRADOR" and changes.get("perfil", "ADMINISTRADOR") != \
                "ADMINISTRADOR" and await _active_admins(s) <= 1:
            raise ConflictError("No se puede dejar al sistema sin administradores activos.")
        created = await create_request(
            uow, tipo="MODIFICACION_USUARIO", entidad="usuario", entidad_id=user_id,
            solicitante_id=p.user_id, motivo=body.motivo,
            items=[Item(k, current.get(k), v) for k, v in sorted(changes.items())])
        await uow.commit()
    return _out(created, user_id)


class ModulosIn(_In):
    modulos: list[str] = Field(max_length=50)
    motivo: str | None = Field(None, max_length=1000)


@router.put("/admin/users/{user_id}/modules", status_code=202, response_model=RequestOut)
async def request_user_modules(
    user_id: uuid.UUID, body: ModulosIn, request: Request,
    p: Principal = Depends(require("ADM.USUARIO.EDICION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> RequestOut:
    async with _uow(request, p, auth) as uow:
        s = uow.session
        u = await _user(s, user_id)
        if u["estado"] != "ACTIVO":
            raise BusinessRuleError("Solo se asignan módulos a usuarios activos.")
        desired = await _module_ids(s, body.modulos)
        current = await _current_modules(s, user_id)
        if desired == current:
            raise BusinessRuleError("No hay cambios respecto de los módulos actuales.")
        if u["perfil"] == "ADMINISTRADOR" and "ADM" not in desired:
            raise ConflictError("Un administrador debe conservar el módulo de Administración.")
        created = await create_request(
            uow, tipo="MODULOS_USUARIO", entidad="usuario", entidad_id=user_id,
            solicitante_id=p.user_id, motivo=body.motivo,
            items=[Item("modulos", current, desired)])
        await uow.commit()
    return _out(created, user_id)


class MotivoIn(_In):
    motivo: str = MOTIVO


@router.post("/admin/users/{user_id}/deactivate", status_code=202, response_model=RequestOut)
async def request_user_deactivation(
    user_id: uuid.UUID, body: MotivoIn, request: Request,
    p: Principal = Depends(require("ADM.USUARIO.ELIMINACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> RequestOut:
    """CU-USR-05 / REQ-USER-08: inhabilitación lógica con motivo; efectiva al aprobarse."""
    async with _uow(request, p, auth) as uow:
        s = uow.session
        u = await _user(s, user_id)
        if u["estado"] != "ACTIVO":
            raise BusinessRuleError("Solo se inhabilitan usuarios activos.")
        if u["perfil"] == "ADMINISTRADOR" and await _active_admins(s) <= 1:
            raise ConflictError("No se puede dejar al sistema sin administradores activos.")
        created = await create_request(
            uow, tipo="INHABILITACION_USUARIO", entidad="usuario", entidad_id=user_id,
            solicitante_id=p.user_id, motivo=body.motivo,
            items=[Item("estado", "ACTIVO", "INACTIVO")])
        await uow.commit()
    return _out(created, user_id)


@router.post("/admin/users/{user_id}/reactivate", status_code=202, response_model=RequestOut)
async def request_user_reactivation(
    user_id: uuid.UUID, body: MotivoIn, request: Request,
    p: Principal = Depends(require("ADM.USUARIO.EDICION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> RequestOut:
    """CU-USR-06 / REQ-AUTH-11: al aplicarse exigirá contraseña temporal y cambio (Fase 6)."""
    async with _uow(request, p, auth) as uow:
        u = await _user(uow.session, user_id)
        if u["estado"] != "INACTIVO":
            raise BusinessRuleError("Solo se reactivan usuarios inactivos.")
        created = await create_request(
            uow, tipo="REACTIVACION_USUARIO", entidad="usuario", entidad_id=user_id,
            solicitante_id=p.user_id, motivo=body.motivo,
            items=[Item("estado", "INACTIVO", "ACTIVO")])
        await uow.commit()
    return _out(created, user_id)


# ============================================================================ DIRECTAS

class TemporalOut(BaseModel):
    contrasena_temporal: str
    mensaje: str


@router.post("/admin/users/{user_id}/password-reset", response_model=TemporalOut)
async def reset_password(
    user_id: uuid.UUID, request: Request, response: Response,
    p: Principal = Depends(require("ADM.USUARIO.EDICION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> TemporalOut:
    """CU-AUTH-05 / REQ-AUTH-06: nueva temporal; nunca se muestra ni recupera la anterior."""
    if user_id == p.user_id:
        raise BusinessRuleError("Use el cambio de contraseña para su propia cuenta.")
    temp = generate_temporary_password()
    async with _uow(request, p, auth) as uow:
        s = uow.session
        u = await _user(s, user_id)
        if u["estado"] != "ACTIVO":
            raise BusinessRuleError("Solo se generan contraseñas temporales para cuentas activas.")
        await auth_repo.set_password(s, user_id, hash_password(temp), must_change=True,
                                     keep=auth.settings.password_history)
        sid = await auth_repo.close_open_session(s, user_id, "REVOCADA_ADMIN")
        uow.audit(AuditEntry(categoria="AUTENTICACION", accion="AUTH_PASSWORD_RESET",
                             modulo="ADM", entidad="usuario", entidad_id=str(user_id),
                             detalle={"sesion_revocada": str(sid) if sid else None}))
        if sid is not None:
            await auth.store.close(user_id, sid)
        await uow.commit()
    response.headers["Cache-Control"] = "no-store"
    return TemporalOut(contrasena_temporal=temp, mensaje=(
        "Se muestra una sola vez. Entréguela por un canal seguro; el usuario deberá "
        "cambiarla en su próximo inicio de sesión."))


@router.post("/admin/users/{user_id}/sessions/revoke")
async def revoke_session(
    user_id: uuid.UUID, request: Request,
    p: Principal = Depends(require("ADM.USUARIO.EDICION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> dict[str, bool]:
    async with _uow(request, p, auth) as uow:
        await _user(uow.session, user_id)
        sid = await auth_repo.close_open_session(uow.session, user_id, "REVOCADA_ADMIN")
        if sid is None:
            return {"revocada": False}
        uow.audit(AuditEntry(categoria="AUTENTICACION", accion="AUTH_SESSION_REVOKED",
                             modulo="ADM", entidad="sesion", entidad_id=str(sid),
                             detalle={"usuario_id": str(user_id), "motivo": "REVOCADA_ADMIN"}))
        await auth.store.close(user_id, sid)
        await uow.commit()
    return {"revocada": True}
