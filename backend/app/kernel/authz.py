"""Autorización por operación en el backend (REQ-IAM-05, P §4.1).

    @router.get(..., dependencies=[...])  →  p: Principal = Depends(require("ADM.USUARIO.CONSULTA"))

Valida, en orden y fail-closed:
  1–4. token, sesión viva, inactividad y cuenta activa      (require_session, Fase 3)
  5.   módulo existente y ACTIVO
  6.   módulo ASIGNADO al usuario
  7.   permiso EFECTIVO (perfil → roles → permisos, todos activos; vista v_permiso_efectivo)
  +    en el módulo ADM, perfil de sistema ADMINISTRADOR (PD-06 APROBADO)
Cada denegación se audita como AUTHZ_DENIED (si la auditoría falla → 503).
Las reglas de negocio específicas se validan después, en cada caso de uso.
"""

import re
from collections.abc import Awaitable, Callable

from fastapi import Depends, Request
from sqlalchemy import text

from app.core.errors import ForbiddenError
from app.kernel.audit import AuditEntry
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.api.dependencies import audit_context, get_auth_service, require_session
from app.modules.auth.application.service import AuthService, Principal

PERMISSION_RE = re.compile(
    r"^([A-Z]{2,16})\.[A-Z][A-Z0-9_]{1,40}\."
    r"(CONSULTA|CREACION|EDICION|ELIMINACION|APROBACION|EXPORTACION)$"
)
ADMIN_MODULE = "ADM"
ADMIN_PROFILE = "ADMINISTRADOR"

_CHECK_SQL = text(
    """
    SELECT m.estado AS modulo_estado,
           EXISTS (SELECT 1 FROM app.usuario_modulo um
                    WHERE um.usuario_id = :u AND um.modulo_id = m.id
                      AND um.estado = 'ACTIVO') AS asignado,
           EXISTS (SELECT 1 FROM app.v_permiso_efectivo v
                    WHERE v.usuario_id = :u AND v.permiso = :p) AS permitido,
           (SELECT pf.codigo FROM app.usuario u JOIN app.perfil pf ON pf.id = u.perfil_id
             WHERE u.id = :u) AS perfil
      FROM (SELECT 1) AS one
      LEFT JOIN app.modulo m ON m.codigo = :m
    """
)


class AuthorizationDeniedError(ForbiddenError):
    code = "FORBIDDEN"


def require(permission: str) -> Callable[..., Awaitable[Principal]]:
    match = PERMISSION_RE.match(permission)
    if not match:
        raise ValueError(f"código de permiso inválido: {permission}")
    module = match.group(1)
    session_dependency = require_session()

    async def dependency(
        request: Request,
        p: Principal = Depends(session_dependency),  # noqa: B008
        auth: AuthService = Depends(get_auth_service),  # noqa: B008
    ) -> Principal:
        async with auth.sm() as s:
            row = (
                await s.execute(_CHECK_SQL, {"u": p.user_id, "p": permission, "m": module})
            ).one()

        if row.modulo_estado is None:
            reason = "MODULO_INEXISTENTE"
        elif row.modulo_estado != "ACTIVO":
            reason = "MODULO_INACTIVO"
        elif not row.asignado:
            reason = "MODULO_NO_ASIGNADO"
        elif not row.permitido:
            reason = "PERMISO_AUSENTE"
        elif module == ADMIN_MODULE and row.perfil != ADMIN_PROFILE:
            reason = "PERFIL_NO_ADMINISTRADOR"
        else:
            return p

        async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
            uow.audit(AuditEntry(
                categoria="AUTORIZACION", accion="AUTHZ_DENIED", resultado="DENEGADO",
                modulo=module,
                detalle={"permiso": permission, "motivo": reason,
                         "metodo": request.method, "ruta": request.url.path},
            ))
            await uow.commit()
        raise AuthorizationDeniedError()

    dependency.__secureone_permission__ = permission  # type: ignore[attr-defined]
    return dependency
