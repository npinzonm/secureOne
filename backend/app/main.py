"""Punto de entrada FastAPI (Fase 1: solo fundamentos y health)."""

import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import health
from app.core.config import get_settings
from app.core.logging import configure_logging, correlation_id_var

API_PREFIX = "/api/v1"
_CID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    is_dev = settings.app_env == "dev"
    app = FastAPI(
        title="SecureOne API",
        version="0.1.0",
        docs_url=f"{API_PREFIX}/docs" if is_dev else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json" if is_dev else None,
    )

    @app.middleware("http")
    async def correlation_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("x-request-id", "")
        cid = incoming if _CID_RE.match(incoming) else str(uuid.uuid4())
        token = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Request-ID"] = cid
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error (%s)", type(exc).__name__, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Error interno.",
                    "correlation_id": correlation_id_var.get(),
                }
            },
        )

    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
