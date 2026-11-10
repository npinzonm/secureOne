"""T-OPS-01, T-OPS-02: health checks."""

from fastapi.testclient import TestClient

from app.api.health import get_checks
from app.main import create_app


async def _ok(_settings) -> None:
    return None


async def _fail(_settings) -> None:
    raise ConnectionError("password=should-not-leak")


def _client(checks) -> TestClient:
    app = create_app(with_lifespan=False)
    app.dependency_overrides[get_checks] = lambda: checks
    return TestClient(app)


def test_live_returns_ok():
    r = _client({}).get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["X-Request-ID"]


def test_ready_ok_when_all_dependencies_ok():
    r = _client({"postgres": _ok, "redis": _ok, "migrations": _ok}).get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "checks": {"postgres": "ok", "redis": "ok", "migrations": "ok"},
    }


def test_ready_503_when_migrations_pending():
    r = _client({"postgres": _ok, "redis": _ok, "migrations": _fail}).get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["migrations"] == "fail"


def test_migrations_head_is_resolvable():
    from app.api.health import migrations_head

    assert migrations_head() == "0005"


def test_ready_503_when_postgres_down():
    r = _client({"postgres": _fail, "redis": _ok}).get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"] == {"postgres": "fail", "redis": "ok"}


def test_ready_503_when_redis_down_and_no_detail_leaked():
    r = _client({"postgres": _ok, "redis": _fail}).get("/api/v1/health/ready")
    assert r.status_code == 503
    assert "should-not-leak" not in r.text


def test_valid_incoming_request_id_is_propagated():
    rid = "abcdef12-3456"
    r = _client({}).get("/api/v1/health/live", headers={"X-Request-ID": rid})
    assert r.headers["X-Request-ID"] == rid


def test_invalid_incoming_request_id_is_replaced():
    r = _client({}).get("/api/v1/health/live", headers={"X-Request-ID": "<script>"})
    assert r.headers["X-Request-ID"] != "<script>"


def test_docs_disabled_outside_dev():
    assert _client({}).get("/api/v1/docs").status_code == 404
