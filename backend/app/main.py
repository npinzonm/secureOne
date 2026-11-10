"""Punto de entrada FastAPI."""

import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import health
from app.core.config import get_settings
from app.core.db import Database
from app.core.errors import error_body, install_error_handlers
from app.core.logging import configure_logging, correlation_id_var
from app.kernel.audit import IncidentSpool
from app.kernel.error_registry import classify, record_error
from app.modules.auth.api.router import router as auth_router
from app.modules.auth.application.service import AuthService
from app.modules.auth.infrastructure.session_store import SessionStore
from app.modules.iam.api.router import router as iam_router
from app.modules.users.api.router import router as users_router

API_PREFIX = "/api/v1"
_CID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.db = Database(settings.sqlalchemy_url)
    app.state.spool = IncidentSpool(settings.spool_dir)
    app.state.redis = aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password.get_secret_value(),
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    app.state.auth = AuthService(
        settings,
        app.state.db.sessionmaker,
        SessionStore(app.state.redis, settings.session_idle_seconds),
        app.state.spool,
    )
    # Recuperación: si quedaron incidentes de auditoría de una caída previa, registrarlos.
    try:
        n = await app.state.spool.flush(app.state.db.sessionmaker)
        if n:
            logger.warning("incidentes de auditoría recuperados al iniciar: %d", n)
    except Exception as exc:  # noqa: BLE001 - se reintenta en el próximo arranque / CLI
        logger.error("no se pudo volcar el spool de incidentes (%s)", type(exc).__name__)
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.db.dispose()


async def _record_unhandled(request: Request, exc: Exception) -> None:
    db = getattr(request.app.state, "db", None)
    if db is None:
        return
    await record_error(
        db.sessionmaker,
        categoria=classify(exc),
        componente="api",
        tipo=type(exc).__name__,
        descripcion=f"Error no controlado en {request.method} {request.url.path}",
        severidad="ALTA",
    )


def create_app(*, with_lifespan: bool = True) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    is_dev = settings.app_env == "dev"
    app = FastAPI(
        title="SecureOne API",
        version="0.4.0",
        docs_url=f"{API_PREFIX}/docs" if is_dev else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json" if is_dev else None,
        lifespan=lifespan if with_lifespan else None,
    )

    @app.middleware("http")
    async def correlation_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("x-request-id", "")
        cid = incoming if _CID_RE.match(incoming) else str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        try:
            try:
                response = await call_next(request)
            except Exception as exc:  # noqa: BLE001
                # Se maneja aquí (y no solo en ServerErrorMiddleware) para conservar el
                # correlation_id en la respuesta y en el registro de errores.
                logger.error("unhandled error (%s)", type(exc).__name__, exc_info=exc)
                await _record_unhandled(request, exc)
                response = JSONResponse(
                    status_code=500, content=error_body("INTERNAL_ERROR", "Error interno.")
                )
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Request-ID"] = cid
        return response

    install_error_handlers(app, on_unhandled=_record_unhandled)
    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(iam_router, prefix=API_PREFIX)
    app.include_router(users_router, prefix=API_PREFIX)
    return app


app = create_app()
