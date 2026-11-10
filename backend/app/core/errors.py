"""Errores de aplicación y formato uniforme de respuesta (REQ-RNF-03).

Formato: {"error": {"code", "message", "correlation_id", "details?"}}
Los mensajes nunca incluyen detalles internos ni valores de entrada (pueden contener secretos).
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import correlation_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    message = "Error interno."

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details


class NotAuthenticatedError(AppError):
    status_code, code, message = 401, "NOT_AUTHENTICATED", "Autenticación requerida."


class ForbiddenError(AppError):
    status_code, code, message = 403, "FORBIDDEN", "No tiene permiso para esta operación."


class NotFoundError(AppError):
    status_code, code, message = 404, "NOT_FOUND", "Recurso no encontrado."


class ConflictError(AppError):
    status_code, code = 409, "CONFLICT"
    message = "La operación entra en conflicto con el estado actual."


class BusinessRuleError(AppError):
    status_code, code = 422, "BUSINESS_RULE"
    message = "La operación no cumple una regla de negocio."


class ServiceUnavailableError(AppError):
    status_code, code = 503, "SERVICE_UNAVAILABLE"
    message = "Servicio no disponible temporalmente. Intente más tarde."


class AuditUnavailableError(ServiceUnavailableError):
    """Fail-closed (REQ-AUD-07): la operación no se ejecutó porque no pudo auditarse."""

    code = "AUDIT_UNAVAILABLE"


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "correlation_id": correlation_id_var.get(),
    }
    if details is not None:
        body["details"] = details
    return {"error": body}


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "TOO_MANY_REQUESTS",
}


def install_error_handlers(app: FastAPI, on_unhandled=None) -> None:  # type: ignore[no-untyped-def]
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Sin 'input' ni 'ctx': podrían contener contraseñas u otros datos enviados.
        details = [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=error_body("VALIDATION_ERROR", "Datos de entrada inválidos.", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else code
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error (%s)", type(exc).__name__, exc_info=exc)
        if on_unhandled is not None:
            await on_unhandled(request, exc)
        return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", "Error interno."))
