"""Endpoints de autenticación (E.2 de docs/04-api-endpoints.md)."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.modules.auth.api.dependencies import (
    audit_context,
    client_ip,
    get_auth_service,
    require_session,
)
from app.modules.auth.application.service import AuthService, IssuedTokens, Principal
from app.modules.auth.infrastructure import repository as repo

router = APIRouter(tags=["auth"])

REFRESH_COOKIE = "so_refresh"
REFRESH_PATH = "/api/v1/auth"


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    usuario_red: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - tipo de token, no un secreto
    expires_in: int
    debe_cambiar_contrasena: bool


class SessionOut(BaseModel):
    restringida: bool
    segundos_restantes_inactividad: int


class MeOut(BaseModel):
    usuario_red: str
    nombre: str
    primer_apellido: str
    segundo_apellido: str | None
    correo: str
    perfil_codigo: str
    perfil_nombre: str
    ultimo_ingreso: str | None


def _set_refresh(response: Response, value: str | None) -> None:
    if value is None:
        response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
        return
    response.set_cookie(
        REFRESH_COOKIE,
        value,
        httponly=True,
        secure=get_settings().refresh_cookie_secure,
        samesite="strict",
        path=REFRESH_PATH,
    )


def _token_out(response: Response, t: IssuedTokens) -> TokenOut:
    _set_refresh(response, t.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return TokenOut(access_token=t.access_token, expires_in=t.expires_in,
                    debe_cambiar_contrasena=t.must_change_password)


@router.post("/auth/login", response_model=TokenOut)
async def login(
    body: LoginIn, request: Request, response: Response,
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> TokenOut:
    tokens = await auth.login(body.usuario_red, body.password, client_ip(request),
                              request.headers.get("user-agent"))
    return _token_out(response, tokens)


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(
    response: Response,
    so_refresh: Annotated[str | None, Cookie()] = None,
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> TokenOut:
    return _token_out(response, await auth.refresh(so_refresh))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response,
    p: Principal = Depends(require_session(allow_restricted=True, touch=False)),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> Response:
    await auth.logout(p, audit_context(request, p))
    response.status_code = status.HTTP_204_NO_CONTENT
    _set_refresh(response, None)
    return response


@router.post("/auth/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeIn, request: Request, response: Response,
    p: Principal = Depends(require_session(allow_restricted=True)),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> Response:
    await auth.change_password(p, body.current_password, body.new_password,
                               audit_context(request, p))
    response.status_code = status.HTTP_204_NO_CONTENT
    _set_refresh(response, None)  # la sesión se cerró: hay que volver a iniciar sesión
    return response


@router.get("/auth/session", response_model=SessionOut)
async def session_status(
    p: Principal = Depends(require_session(allow_restricted=True, touch=False)),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> SessionOut:
    return SessionOut(restringida=p.restricted,
                      segundos_restantes_inactividad=await auth.remaining_seconds(p))


@router.get("/me", response_model=MeOut)
async def me(
    p: Principal = Depends(require_session()),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> MeOut:
    async with auth.sm() as s:
        data = await repo.get_me(s, p.user_id)
    if data is None:
        raise NotFoundError()
    data["ultimo_ingreso"] = data["ultimo_ingreso"].isoformat() if data["ultimo_ingreso"] else None
    return MeOut(**data)
