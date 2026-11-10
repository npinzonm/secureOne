"""Resolución de solicitudes (CU-APR-02..04; D-APR-001/002 APROBADOS).

- UNA aprobación basta; cualquiera de los administradores, incluido el solicitante.
- La aprobación APLICA todos los ítems en la misma transacción que la marca la solicitud como
  APROBADA y que los eventos de auditoría: todo o nada (si algo falla, sigue PENDIENTE).
- Antes de aplicar se revalida (PROPUESTO, ESP-APR R8): valor_anterior == valor actual,
  catálogos/perfil/módulos activos y reglas de administradores.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.kernel.audit import AuditEntry
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.domain.password_policy import generate_temporary_password
from app.modules.auth.infrastructure import repository as auth_repo
from app.modules.auth.infrastructure.hashing import hash_password
from app.modules.auth.infrastructure.session_store import SessionStore
from app.modules.iam.application.associations import set_active
from app.modules.notifications.application.outbox import notify, request_context
from app.modules.users.application.validators import (
    active_admins,
    active_id,
    current_modules,
    load_user,
    module_codes,
    record_state,
    validate_org,
)

CAT = "APROBACIONES"
USER_FIELDS = ("identificacion", "nombre", "primer_apellido", "segundo_apellido", "correo",
               "gerencia_id", "area_id", "cargo_id")


class AlreadyResolvedError(ConflictError):
    code = "REQUEST_ALREADY_RESOLVED"
    message = "La solicitud ya fue resuelta."


class SnapshotMismatchError(ConflictError):
    code = "SNAPSHOT_MISMATCH"
    message = ("El registro cambió desde que se creó la solicitud. Cancélela y cree una nueva "
               "vinculada.")


class AdminLimitError(ConflictError):
    code = "ADMIN_LIMIT"
    message = "Se alcanzaría el máximo de dos administradores activos."


@dataclass(frozen=True)
class Resolution:
    solicitud_id: uuid.UUID
    numero: int
    tipo: str
    estado: str
    usuario_id: uuid.UUID
    contrasena_temporal: str | None = None


async def _lock_pending(uow: UnitOfWork, rid: uuid.UUID) -> dict[str, Any]:
    sol = (await uow.session.execute(text(
        "SELECT * FROM app.solicitud WHERE id = :i FOR UPDATE"), {"i": rid})).mappings().first()
    if sol is None:
        raise NotFoundError()
    if sol["estado"] != "PENDIENTE":
        raise AlreadyResolvedError(details={"estado": sol["estado"]})
    return dict(sol)


async def _items(uow: UnitOfWork, rid: uuid.UUID) -> dict[str, tuple[Any, Any]]:
    rows = await uow.session.execute(text(
        "SELECT atributo, valor_anterior, valor_nuevo FROM app.solicitud_item "
        "WHERE solicitud_id = :i ORDER BY orden"), {"i": rid})
    return {r[0]: (r[1], r[2]) for r in rows}


def _norm(v: Any) -> Any:
    return str(v) if isinstance(v, uuid.UUID) else v


async def _exec_guarded(uow: UnitOfWork, sql: str, params: dict[str, Any]) -> None:
    """Ejecuta un UPDATE que puede disparar el trigger de máximo de administradores."""
    try:
        async with uow.session.begin_nested():
            await uow.session.execute(text(sql), params)
    except IntegrityError as exc:
        if "administradores" in str(exc.orig):
            raise AdminLimitError() from exc
        raise ConflictError() from exc


async def _issue_temp(uow: UnitOfWork, uid: uuid.UUID, settings: Settings, exists: bool) -> str:
    temp = generate_temporary_password()
    h = hash_password(temp)
    if exists:
        await auth_repo.set_password(uow.session, uid, h, must_change=True,
                                     keep=settings.password_history)
    else:
        await uow.session.execute(text(
            "INSERT INTO app.credencial (usuario_id, password_hash, debe_cambiar) "
            "VALUES (:u, :h, true)"), {"u": uid, "h": h})
        await auth_repo.add_password_history(uow.session, uid, h, settings.password_history)
    return temp


async def _module_map(uow: UnitOfWork, codes: list[str]) -> dict[str, uuid.UUID]:
    rows = await uow.session.execute(text(
        "SELECT codigo, id FROM app.modulo WHERE codigo = ANY(:c)"), {"c": codes})
    return {r[0]: r[1] for r in rows}


# =========================================================================== aplicación por tipo

async def _apply_alta(uow, sol, items, u, approver, settings) -> str:
    if u["estado"] != "PENDIENTE_ALTA":
        raise SnapshotMismatchError(details={"estado_actual": u["estado"]})
    perfil = items["perfil"][1]
    await active_id(uow.session, "SELECT id, estado FROM app.perfil WHERE codigo = :v", perfil,
                    "El perfil")
    await validate_org(uow.session, u["gerencia_id"], u["area_id"], u["cargo_id"])
    modulos = await module_codes(uow.session, items["modulos"][1])
    await _exec_guarded(uow, "UPDATE app.usuario SET estado = 'ACTIVO', modificado_en = now(), "
                             "modificado_por = :a WHERE id = :u",
                        {"a": approver, "u": u["id"]})
    temp = await _issue_temp(uow, u["id"], settings, exists=False)
    await set_active(uow.session, "usuario_modulo", u["id"],
                     await _module_map(uow, modulos), approver)
    await record_state(uow.session, u["id"], "PENDIENTE_ALTA", "ACTIVO",
                       f"Alta aprobada (solicitud {sol['numero']})", approver, sol["id"])
    uow.audit(AuditEntry(categoria="USUARIOS", accion="USR_CREATED", modulo="ADM",
                         entidad="usuario", entidad_id=str(u["id"]), solicitud_id=sol["id"],
                         valor_nuevo={k: v[1] for k, v in items.items()}))
    return temp


async def _apply_modificacion(uow, sol, items, u, approver) -> None:
    s = uow.session
    if u["estado"] != "ACTIVO":
        raise SnapshotMismatchError(details={"estado_actual": u["estado"]})
    for attr, (anterior, _) in items.items():
        if _norm(u[attr]) != anterior:  # incluye "perfil" (código), ver load_user
            raise SnapshotMismatchError(details={"atributo": attr})
    new = {k: v[1] for k, v in items.items()}
    if "identificacion" in new and (await s.execute(text(
            "SELECT 1 FROM app.usuario WHERE identificacion = :i AND id <> :u"),
            {"i": new["identificacion"], "u": u["id"]})).first():
        raise ConflictError("La identificación ya existe.")
    sets: dict[str, Any] = {k: v for k, v in new.items() if k in USER_FIELDS}
    if "perfil" in new:
        sets["perfil_id"] = await active_id(
            s, "SELECT id, estado FROM app.perfil WHERE codigo = :v", new["perfil"], "El perfil")
        if u["perfil"] == "ADMINISTRADOR" and new["perfil"] != "ADMINISTRADOR" \
                and await active_admins(s) <= 1:
            raise ConflictError("No se puede dejar al sistema sin administradores activos.")
    if {"gerencia_id", "area_id", "cargo_id"} & new.keys():
        await validate_org(s, *(uuid.UUID(str(new.get(k, u[k])))
                                for k in ("gerencia_id", "area_id", "cargo_id")))
    assigns = ", ".join(f"{k} = :{k}" for k in sets)
    await _exec_guarded(uow, f"UPDATE app.usuario SET {assigns}, modificado_en = now(), "  # noqa: S608
                             "modificado_por = :p_actor WHERE id = :p_uid",
                        {**sets, "p_actor": approver, "p_uid": u["id"]})
    uow.audit(AuditEntry(categoria="USUARIOS", accion="USR_UPDATED", modulo="ADM",
                         entidad="usuario", entidad_id=str(u["id"]), solicitud_id=sol["id"],
                         valor_anterior={k: v[0] for k, v in items.items()}, valor_nuevo=new))


async def _apply_modulos(uow, sol, items, u, approver) -> None:
    if u["estado"] != "ACTIVO":
        raise SnapshotMismatchError(details={"estado_actual": u["estado"]})
    anterior, nuevo = items["modulos"]
    if await current_modules(uow.session, u["id"]) != anterior:
        raise SnapshotMismatchError(details={"atributo": "modulos"})
    desired = await module_codes(uow.session, nuevo)
    if u["perfil"] == "ADMINISTRADOR" and "ADM" not in desired:
        raise ConflictError("Un administrador debe conservar el módulo de Administración.")
    before, after = await set_active(uow.session, "usuario_modulo", u["id"],
                                     await _module_map(uow, desired), approver)
    uow.audit(AuditEntry(categoria="IAM", accion="IAM_USER_MODULES", modulo="ADM",
                         entidad="usuario", entidad_id=str(u["id"]), solicitud_id=sol["id"],
                         valor_anterior={"modulos": before}, valor_nuevo={"modulos": after}))


async def _apply_inhabilitacion(uow, sol, u, approver, store: SessionStore) -> None:
    if u["estado"] != "ACTIVO":
        raise SnapshotMismatchError(details={"estado_actual": u["estado"]})
    if u["perfil"] == "ADMINISTRADOR" and await active_admins(uow.session) <= 1:
        raise ConflictError("No se puede dejar al sistema sin administradores activos.")
    await uow.session.execute(text(
        "UPDATE app.usuario SET estado = 'INACTIVO', modificado_en = now(), modificado_por = :a "
        "WHERE id = :u"), {"a": approver, "u": u["id"]})
    sid = await auth_repo.close_open_session(uow.session, u["id"], "INHABILITACION")
    await record_state(uow.session, u["id"], "ACTIVO", "INACTIVO", sol["motivo"] or "",
                       approver, sol["id"])
    uow.audit(AuditEntry(categoria="USUARIOS", accion="USR_DEACTIVATED", modulo="ADM",
                         entidad="usuario", entidad_id=str(u["id"]), solicitud_id=sol["id"],
                         motivo=sol["motivo"], valor_anterior={"estado": "ACTIVO"},
                         valor_nuevo={"estado": "INACTIVO"},
                         detalle={"sesion_revocada": str(sid) if sid else None}))
    if sid is not None:  # REQ-AUTH-10: invalidación inmediata (antes del commit; fail-closed)
        await store.close(u["id"], sid)


async def _apply_reactivacion(uow, sol, u, approver, settings) -> str:
    if u["estado"] != "INACTIVO":
        raise SnapshotMismatchError(details={"estado_actual": u["estado"]})
    has_cred = (await uow.session.execute(text(
        "SELECT 1 FROM app.credencial WHERE usuario_id = :u"), {"u": u["id"]})).first()
    if not has_cred:
        raise BusinessRuleError("El usuario nunca fue activado; corrija el alta con una "
                                "solicitud vinculada.")
    await _exec_guarded(uow, "UPDATE app.usuario SET estado = 'ACTIVO', modificado_en = now(), "
                             "modificado_por = :a WHERE id = :u",
                        {"a": approver, "u": u["id"]})
    temp = await _issue_temp(uow, u["id"], settings, exists=True)  # REQ-AUTH-11
    await record_state(uow.session, u["id"], "INACTIVO", "ACTIVO", sol["motivo"] or "",
                       approver, sol["id"])
    uow.audit(AuditEntry(categoria="USUARIOS", accion="USR_REACTIVATED", modulo="ADM",
                         entidad="usuario", entidad_id=str(u["id"]), solicitud_id=sol["id"],
                         motivo=sol["motivo"], valor_anterior={"estado": "INACTIVO"},
                         valor_nuevo={"estado": "ACTIVO", "debe_cambiar_contrasena": True}))
    return temp


# =========================================================================== casos de uso

async def approve(uow: UnitOfWork, rid: uuid.UUID, approver: uuid.UUID, settings: Settings,
                  store: SessionStore, comentario: str | None) -> Resolution:
    sol = await _lock_pending(uow, rid)
    items = await _items(uow, rid)
    u = await load_user(uow.session, sol["entidad_id"])
    temp = None
    tipo = sol["tipo"]
    if tipo == "ALTA_USUARIO":
        temp = await _apply_alta(uow, sol, items, u, approver, settings)
    elif tipo == "MODIFICACION_USUARIO":
        await _apply_modificacion(uow, sol, items, u, approver)
    elif tipo == "MODULOS_USUARIO":
        await _apply_modulos(uow, sol, items, u, approver)
    elif tipo == "INHABILITACION_USUARIO":
        await _apply_inhabilitacion(uow, sol, u, approver, store)
    elif tipo == "REACTIVACION_USUARIO":
        temp = await _apply_reactivacion(uow, sol, u, approver, settings)
    else:  # pragma: no cover - tipos de TH llegan en la Fase 8
        raise BusinessRuleError("Tipo de solicitud no soportado.")
    await _resolve(uow, sol, "APROBADA", approver, comentario)
    uow.audit(AuditEntry(
        categoria=CAT, accion="APR_APPROVED", modulo="ADM", entidad="solicitud",
        entidad_id=str(rid), solicitud_id=rid, motivo=comentario,
        detalle={"numero": sol["numero"], "tipo": tipo, "solicitante": str(sol["solicitante_id"]),
                 "aprobador": str(approver),
                 "autoaprobacion": sol["solicitante_id"] == approver}))
    await notify(uow, "APR_APPROVED", str(rid),
                 await request_context(uow.session, rid, uow.ctx.actor_usuario_red))
    return Resolution(rid, sol["numero"], tipo, "APROBADA", u["id"], temp)


async def reject_or_cancel(uow: UnitOfWork, rid: uuid.UUID, actor: uuid.UUID, motivo: str,
                           estado: str) -> Resolution:
    sol = await _lock_pending(uow, rid)
    await _resolve(uow, sol, estado, actor, motivo)
    if sol["tipo"] == "ALTA_USUARIO":  # ESP-ADM-USR R5 (PROPUESTO): se conserva INACTIVO
        await uow.session.execute(text(
            "UPDATE app.usuario SET estado = 'INACTIVO', modificado_en = now(), "
            "modificado_por = :a WHERE id = :u AND estado = 'PENDIENTE_ALTA'"),
            {"a": actor, "u": sol["entidad_id"]})
        await record_state(uow.session, sol["entidad_id"], "PENDIENTE_ALTA", "INACTIVO",
                           f"Alta {estado.lower()}: {motivo}", actor, rid)
    uow.audit(AuditEntry(
        categoria=CAT, accion="APR_REJECTED" if estado == "RECHAZADA" else "APR_CANCELLED",
        modulo="ADM", entidad="solicitud", entidad_id=str(rid), solicitud_id=rid, motivo=motivo,
        detalle={"numero": sol["numero"], "tipo": sol["tipo"]}))
    await notify(uow, "APR_REJECTED" if estado == "RECHAZADA" else "APR_CANCELLED", str(rid),
                 await request_context(uow.session, rid, uow.ctx.actor_usuario_red))
    return Resolution(rid, sol["numero"], sol["tipo"], estado, sol["entidad_id"])


async def _resolve(uow: UnitOfWork, sol: dict, estado: str, actor: uuid.UUID,
                   motivo: str | None) -> None:
    await uow.session.execute(text(
        "UPDATE app.solicitud SET estado = :e, resuelta_por_id = :a, resuelta_en = now(), "
        "motivo_resolucion = :m WHERE id = :i"),
        {"e": estado, "a": actor, "m": motivo, "i": sol["id"]})
