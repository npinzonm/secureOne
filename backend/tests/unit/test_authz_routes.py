"""T-SEC-00: toda ruta no pública declara una guarda; códigos de permiso válidos."""

import pytest
from fastapi.routing import APIRoute

from app.kernel.authz import require
from app.main import create_app

PUBLIC = {
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
}
SESSION_ONLY = {
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/password/change"),
    ("GET", "/api/v1/auth/session"),
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/me/modules"),
    ("GET", "/api/v1/me/permissions"),
    ("GET", "/api/v1/notifications"),
    ("GET", "/api/v1/notifications/count"),
    ("POST", "/api/v1/notifications/{delivery_id}/read"),
}


def _markers(dependant) -> tuple[set[str], bool]:
    perms, session = set(), False
    stack = list(dependant.dependencies)
    while stack:
        d = stack.pop()
        perm = getattr(d.call, "__secureone_permission__", None)
        if perm:
            perms.add(perm)
        if getattr(d.call, "__secureone_session__", False):
            session = True
        stack.extend(d.dependencies)
    return perms, session


def _routes():
    for r in create_app(with_lifespan=False).routes:
        if isinstance(r, APIRoute):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                yield m, r.path, r


def test_every_non_public_route_is_guarded():
    unguarded, wrong = [], []
    for method, path, route in _routes():
        key = (method, path)
        perms, session = _markers(route.dependant)
        if key in PUBLIC:
            continue
        if key in SESSION_ONLY:
            if not session:
                unguarded.append(key)
            continue
        if not perms:
            unguarded.append(key)
        elif path.startswith("/api/v1/admin/") and not all(p.startswith("ADM.") for p in perms):
            wrong.append((key, perms))
    assert unguarded == [], f"rutas sin guarda: {unguarded}"
    assert wrong == [], f"rutas /admin con permisos fuera de ADM: {wrong}"


def test_public_and_session_sets_match_real_routes():
    keys = {(m, p) for m, p, _ in _routes()}
    assert keys >= PUBLIC | SESSION_ONLY


@pytest.mark.parametrize(
    "bad", ["ADM.USUARIO", "adm.usuario.consulta", "ADM.USUARIO.LEER", "X.Y.CONSULTA", ""]
)
def test_require_rejects_invalid_permission_codes(bad):
    with pytest.raises(ValueError):
        require(bad)


def test_openapi_never_mentions_empresa():
    schema = str(create_app(with_lifespan=False).openapi()).lower()
    assert "empresa" not in schema
