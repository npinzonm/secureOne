"""Formato uniforme de errores (REQ-RNF-03)."""

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import AuditUnavailableError, ConflictError
from app.main import create_app


class Body(BaseModel):
    usuario_red: str
    password: str


def _client() -> TestClient:
    app = create_app(with_lifespan=False)

    @app.get("/_t/conflict")
    async def conflict():
        raise ConflictError(details={"campo": "usuario_red"})

    @app.get("/_t/audit")
    async def audit():
        raise AuditUnavailableError()

    @app.post("/_t/validate")
    async def validate(body: Body):
        return {"ok": True}

    @app.get("/_t/boom")
    async def boom():
        raise RuntimeError("detalle interno con password=Secreto123")

    return TestClient(app, raise_server_exceptions=False)


def test_app_error_format():
    r = _client().get("/_t/conflict")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "CONFLICT"
    assert err["details"] == {"campo": "usuario_red"}
    assert err["correlation_id"] == r.headers["X-Request-ID"]


def test_audit_unavailable_is_503():
    r = _client().get("/_t/audit")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "AUDIT_UNAVAILABLE"


def test_validation_error_never_echoes_input():
    r = _client().post("/_t/validate", json={"password": "Secreto123!", "extra": 1})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "Secreto123!" not in r.text


def test_unknown_route_404_format():
    r = _client().get("/api/v1/no-existe")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_unhandled_error_is_500_without_internal_detail():
    r = _client().get("/_t/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "Secreto123" not in r.text
    assert "detalle interno" not in r.text
    assert r.json()["error"]["correlation_id"] == r.headers["X-Request-ID"]
