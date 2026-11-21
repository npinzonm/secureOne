"""Dependencias de autenticación reutilizables por todas las rutas protegidas.

`require_session()` ejecuta las condiciones 1–4 de REQ-IAM-05 (token, sesión viva, inactividad,
cuenta activa). Las condiciones 5–7 (módulo y permiso) se añaden en la Fase 4.
"""

import ipaddress
from collections.abc import Awaitable, Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.kernel.audit import AuditContext
from app.modules.auth.application.service import AuthService, Principal

_bearer = HTTPBearer(auto_error=False)


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def client_ip(request: Request) -> str | None:
    """IP de origen validada (columna inet). Nginx sobrescribe X-Real-IP con la IP real.

    Cualquier valor que no sea una IP válida se descarta (None) en vez de romper la operación.
    """
    for candidate in (
        request.headers.get("x-real-ip"),
        request.client.host if request.client else None,
    ):
        if candidate:
            try:
                return str(ipaddress.ip_address(candidate.strip()))
            except ValueError:
                continue
    return None


def audit_context(request: Request, p: Principal | None = None) -> AuditContext:
    return AuditContext(
        actor_id=p.user_id if p else None,
        actor_usuario_red=p.usuario_red if p else None,
        ip_origen=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


def require_session(
    *, allow_restricted: bool = False, touch: bool = True
) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
        auth: AuthService = Depends(get_auth_service),  # noqa: B008
    ) -> Principal:
        token = creds.credentials if creds and creds.scheme.lower() == "bearer" else None
        return await auth.authenticate(token, allow_restricted=allow_restricted, touch=touch)

    # Marca para la meta-prueba T-SEC-00 (toda ruta no pública declara una guarda).
    dependency.__secureone_session__ = True  # type: ignore[attr-defined]
    return dependency
