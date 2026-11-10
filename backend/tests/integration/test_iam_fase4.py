"""Integración Fase 4: permisos efectivos, guarda de autorización (batería T-SEC) y consultas."""

import re
import uuid
from contextlib import contextmanager

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.modules.auth.infrastructure.tokens import issue_access_token
from tests.integration.helpers import (
    bearer,
    ensure_profile,
    ensure_role,
    login,
    make_admin,
    make_user,
    token,
)

pytestmark = pytest.mark.integration
S = get_settings()


@pytest.fixture
def client():
    with TestClient(create_app(), base_url="https://testserver",
                    raise_server_exceptions=False) as c:
        yield c


def protected_admin_routes() -> list[tuple[str, str, str]]:
    """Todas las rutas /admin (todos los métodos), con ids de ejemplo: (método, ruta, permiso).

    La guarda se resuelve antes que el cuerpo, así que un cuerpo vacío basta para 401/403.
    """
    out = []
    for r in create_app(with_lifespan=False).routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api/v1/admin/"):
            stack, perm = list(r.dependant.dependencies), None
            while stack:
                d = stack.pop()
                perm = perm or getattr(d.call, "__secureone_permission__", None)
                stack.extend(d.dependencies)
            path = re.sub(r"\{[a-z_]+\}", str(uuid.uuid4()), r.path)
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                out.append((m, path, perm))
    assert len(out) >= 40
    return out


ROUTES = protected_admin_routes()
GET_ROUTES = [(m, p, perm) for m, p, perm in ROUTES if m == "GET"]


def assert_all(client, headers, expected: int, code: str | None = None):
    for method, path, _ in ROUTES:
        r = client.request(method, path, headers=headers,
                           json=None if method == "GET" else {})
        assert r.status_code == expected, (method, path, r.status_code, r.text)
        if code:
            assert r.json()["error"]["code"] == code, (method, path, r.text)


@contextmanager
def temporarily(owner, sql_on: str, sql_off: str, params=()):
    owner.execute(sql_on, params)
    try:
        yield
    finally:
        owner.execute(sql_off, params)


def last_denial(owner, uid) -> dict:
    return owner.execute(
        "SELECT detalle FROM audit.evento WHERE accion = 'AUTHZ_DENIED' AND actor_id = %s "
        "ORDER BY seq DESC LIMIT 1", (uid,)).fetchone()[0]


# --------------------------------------------------------------------------- §1 permisos efectivos

def test_effective_permissions_view(owner):
    ensure_role(owner, "ZZ_R1", ("ADM.PERFIL.CONSULTA", "ADM.ROL.CONSULTA"))
    ensure_role(owner, "ZZ_R2", ("ADM.ROL.CONSULTA", "ADM.MODULO.CONSULTA"))
    ensure_profile(owner, "ZZ_PERFIL_EF", ("ZZ_R1", "ZZ_R2"))
    uid, _ = make_user(owner, perfil="ZZ_PERFIL_EF", modulos=("ADM",))

    def perms():
        return sorted(r[0] for r in owner.execute(
            "SELECT permiso FROM app.v_permiso_efectivo WHERE usuario_id = %s", (uid,)))

    assert perms() == ["ADM.MODULO.CONSULTA", "ADM.PERFIL.CONSULTA", "ADM.ROL.CONSULTA"]

    with temporarily(owner, "UPDATE app.permiso SET estado='INACTIVO' WHERE codigo=%s",
                     "UPDATE app.permiso SET estado='ACTIVO' WHERE codigo=%s",
                     ("ADM.MODULO.CONSULTA",)):
        assert "ADM.MODULO.CONSULTA" not in perms()
    with temporarily(owner, "UPDATE app.rol SET estado='INACTIVO' WHERE codigo='ZZ_R1'",
                     "UPDATE app.rol SET estado='ACTIVO' WHERE codigo='ZZ_R1'"):
        assert perms() == ["ADM.MODULO.CONSULTA", "ADM.ROL.CONSULTA"]  # ROL llega por ZZ_R2
    with temporarily(owner, "UPDATE app.perfil_rol SET estado='INACTIVO' WHERE rol_id="
                            "(SELECT id FROM app.rol WHERE codigo='ZZ_R2')",
                     "UPDATE app.perfil_rol SET estado='ACTIVO' WHERE rol_id="
                     "(SELECT id FROM app.rol WHERE codigo='ZZ_R2')"):
        assert perms() == ["ADM.PERFIL.CONSULTA", "ADM.ROL.CONSULTA"]
    with temporarily(owner, "UPDATE app.perfil SET estado='INACTIVO' WHERE codigo='ZZ_PERFIL_EF'",
                     "UPDATE app.perfil SET estado='ACTIVO' WHERE codigo='ZZ_PERFIL_EF'"):
        assert perms() == []
    with temporarily(owner, "UPDATE app.usuario_modulo SET estado='INACTIVO' WHERE usuario_id=%s",
                     "UPDATE app.usuario_modulo SET estado='ACTIVO' WHERE usuario_id=%s", (uid,)):
        assert perms() == []
    with temporarily(owner, "UPDATE app.usuario SET estado='INACTIVO' WHERE id=%s",
                     "UPDATE app.usuario SET estado='ACTIVO' WHERE id=%s", (uid,)):
        assert perms() == []


def test_permission_must_belong_to_its_module(owner):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute("INSERT INTO app.permiso (codigo, nombre, categoria, modulo_id) "
                      "SELECT 'IND.X.CONSULTA', 'x', 'CONSULTA', id FROM app.modulo "
                      "WHERE codigo = 'ADM'")
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute("INSERT INTO app.permiso (codigo, nombre, categoria, modulo_id) "
                      "SELECT 'ADM.X.CONSULTA', 'x', 'EDICION', id FROM app.modulo "
                      "WHERE codigo = 'ADM'")


def test_admin_has_all_adm_permissions(client, owner):
    _, red = make_admin(owner)
    tok = token(client, red)
    perms = client.get("/api/v1/me/permissions", headers=bearer(tok)).json()
    total = owner.execute(
        "SELECT count(*) FROM app.permiso WHERE codigo LIKE 'ADM.%'").fetchone()[0]
    assert len(perms) == total == len(set(perms))
    for _, path, _ in GET_ROUTES:
        r = client.get(path, headers=bearer(tok))
        assert r.status_code in (200, 404), (path, r.text)  # 404: id de ejemplo inexistente


# --------------------------------------------------------------------------- §2 batería 401

def test_401_battery(client, owner):
    uid, red = make_admin(owner)
    assert_all(client, {}, 401)
    assert_all(client, bearer("no.es.un.jwt"), 401)

    t1 = token(client, red)
    sid = owner.execute("SELECT id FROM app.sesion WHERE usuario_id=%s AND finalizada_en IS NULL",
                        (uid,)).fetchone()[0]
    expired = issue_access_token(S.jwt_secret.get_secret_value(), uid, sid, "access", -5)
    assert_all(client, bearer(expired), 401, "SESSION_ENDED")

    t2 = token(client, red)                       # sesión reemplazada
    assert_all(client, bearer(t1), 401, "SESSION_ENDED")

    client.post("/api/v1/auth/logout", headers=bearer(t2))  # sesión revocada
    assert_all(client, bearer(t2), 401, "SESSION_ENDED")

    t3 = token(client, red)                       # cuenta inactiva con token vigente
    owner.execute("UPDATE app.usuario SET estado='INACTIVO' WHERE id=%s", (uid,))
    assert_all(client, bearer(t3), 401, "SESSION_ENDED")


# --------------------------------------------------------------------------- §3-4 batería 403

def test_403_module_inactive(client, owner):
    uid, red = make_admin(owner)
    tok = token(client, red)
    with temporarily(owner, "UPDATE app.modulo SET estado='INACTIVO' WHERE codigo='ADM'",
                     "UPDATE app.modulo SET estado='ACTIVO' WHERE codigo='ADM'"):
        assert_all(client, bearer(tok), 403, "FORBIDDEN")
        assert last_denial(owner, uid)["motivo"] == "MODULO_INACTIVO"
        assert client.get("/api/v1/me/modules", headers=bearer(tok)).json()["modulos"] == []


def test_403_module_not_assigned(client, owner):
    uid, red = make_admin(owner)
    tok = token(client, red)
    owner.execute("UPDATE app.usuario_modulo SET estado='INACTIVO' WHERE usuario_id=%s", (uid,))
    assert_all(client, bearer(tok), 403)
    assert last_denial(owner, uid)["motivo"] == "MODULO_NO_ASIGNADO"


def test_403_role_and_profile_inactive(client, owner):
    uid, red = make_admin(owner)
    tok = token(client, red)
    with temporarily(owner,
                     "UPDATE app.rol SET estado='INACTIVO' WHERE codigo='ADMINISTRADOR_TOTAL'",
                     "UPDATE app.rol SET estado='ACTIVO' WHERE codigo='ADMINISTRADOR_TOTAL'"):
        assert_all(client, bearer(tok), 403)
        assert last_denial(owner, uid)["motivo"] == "PERMISO_AUSENTE"
    with temporarily(owner,
                     "UPDATE app.perfil SET estado='INACTIVO' WHERE codigo='ADMINISTRADOR'",
                     "UPDATE app.perfil SET estado='ACTIVO' WHERE codigo='ADMINISTRADOR'"):
        assert_all(client, bearer(tok), 403)
    assert client.get("/api/v1/admin/profiles", headers=bearer(tok)).status_code == 200


def test_403_single_permission_inactive_only_affects_its_routes(client, owner):
    uid, red = make_admin(owner)
    tok = token(client, red)
    with temporarily(owner, "UPDATE app.permiso SET estado='INACTIVO' WHERE codigo=%s",
                     "UPDATE app.permiso SET estado='ACTIVO' WHERE codigo=%s",
                     ("ADM.ROL.CONSULTA",)):
        assert client.get("/api/v1/admin/roles", headers=bearer(tok)).status_code == 403
        assert last_denial(owner, uid) == {
            "permiso": "ADM.ROL.CONSULTA", "motivo": "PERMISO_AUSENTE",
            "metodo": "GET", "ruta": "/api/v1/admin/roles"}
        assert client.get("/api/v1/admin/profiles", headers=bearer(tok)).status_code == 200


def test_403_functional_user_without_permission_or_admin_profile(client, owner):
    # Sin módulo ADM: no puede ver fichas de otros usuarios (REQ-USER-09).
    uid, red = make_user(owner)
    other, _ = make_user(owner)
    tok = token(client, red)
    r = client.get(f"/api/v1/admin/users/{other}", headers=bearer(tok))
    assert r.status_code == 403
    assert last_denial(owner, uid)["motivo"] == "MODULO_NO_ASIGNADO"

    # Con módulo ADM pero sin el permiso.
    uid2, red2 = make_user(owner, modulos=("ADM",))
    tok2 = token(client, red2)
    assert_all(client, bearer(tok2), 403)
    assert last_denial(owner, uid2)["motivo"] == "PERMISO_AUSENTE"

    # Con el permiso por un rol propio, pero perfil distinto de ADMINISTRADOR (PD-06).
    ensure_role(owner, "ZZ_CONSULTA_PERFILES", ("ADM.PERFIL.CONSULTA",))
    ensure_profile(owner, "ZZ_NO_ADMIN", ("ZZ_CONSULTA_PERFILES",))
    uid3, red3 = make_user(owner, perfil="ZZ_NO_ADMIN", modulos=("ADM",))
    r = client.get("/api/v1/admin/profiles", headers=bearer(token(client, red3)))
    assert r.status_code == 403
    assert last_denial(owner, uid3)["motivo"] == "PERFIL_NO_ADMINISTRADOR"


def test_403_restricted_token(client, owner):
    _, red = make_admin(owner, must_change=True)
    tok = login(client, red).json()["access_token"]
    assert_all(client, bearer(tok), 403, "PASSWORD_CHANGE_REQUIRED")


def test_denial_is_fail_closed_when_audit_unavailable(client, owner):
    _, red = make_user(owner)
    tok = token(client, red)
    role = S.app_db_user
    with temporarily(owner, f'REVOKE INSERT ON audit.evento FROM "{role}"',
                     f'GRANT INSERT ON audit.evento TO "{role}"'):
        r = client.get("/api/v1/admin/profiles", headers=bearer(tok))
    assert r.status_code == 503 and r.json()["error"]["code"] == "AUDIT_UNAVAILABLE"


# --------------------------------------------------------------------------- §6 /me/modules

def test_my_modules_order_and_empty_message(client, owner):
    _, red = make_user(owner)
    r = client.get("/api/v1/me/modules", headers=bearer(token(client, red)))
    assert r.status_code == 200
    assert r.json()["modulos"] == [] and "No tiene módulos asignados" in r.json()["mensaje"]

    _, red2 = make_user(owner, modulos=("IND", "ADM"))
    tok2 = token(client, red2)
    mods = client.get("/api/v1/me/modules", headers=bearer(tok2)).json()
    assert [m["codigo"] for m in mods["modulos"]] == ["ADM", "IND"] and mods["mensaje"] is None
    with temporarily(owner, "UPDATE app.modulo SET estado='INACTIVO' WHERE codigo='IND'",
                     "UPDATE app.modulo SET estado='ACTIVO' WHERE codigo='IND'"):
        mods = client.get("/api/v1/me/modules", headers=bearer(tok2)).json()["modulos"]
        assert [m["codigo"] for m in mods] == ["ADM"]


# --------------------------------------------------------------------------- §7-8 usuarios

def test_users_list_filters_and_no_audit(client, owner):
    _, red = make_admin(owner)
    tok = token(client, red)
    target, target_red = make_user(owner, estado="INACTIVO")
    before = owner.execute("SELECT max(seq) FROM audit.evento").fetchone()[0]

    r = client.get("/api/v1/admin/users", params={"usuario_red": target_red.upper()},
                   headers=bearer(tok))
    assert r.status_code == 200 and r.json()["total"] == 1
    item = r.json()["items"][0]
    assert item["id"] == str(target) and item["estado"] == "INACTIVO"
    assert "empresa" not in str(item).lower()

    r = client.get("/api/v1/admin/users", params={"estado": "INACTIVO", "page_size": 100},
                   headers=bearer(tok))
    assert all(i["estado"] == "INACTIVO" for i in r.json()["items"])
    # Comodines del usuario se tratan como texto literal.
    assert client.get("/api/v1/admin/users", params={"nombre": "%"},
                      headers=bearer(tok)).json()["total"] == 0
    assert client.get("/api/v1/admin/users", params={"page_size": 101},
                      headers=bearer(tok)).status_code == 422
    after = owner.execute("SELECT max(seq) FROM audit.evento").fetchone()[0]
    assert after == before  # D-AUD-001: los listados no se auditan


def test_user_detail_and_activity_are_audited(client, owner):
    admin, red = make_admin(owner)
    tok = token(client, red)
    target, target_red = make_user(owner, modulos=("IND",))
    login(client, target_red, "Equivocada#2026")

    r = client.get(f"/api/v1/admin/users/{target}", headers=bearer(tok))
    assert r.status_code == 200 and r.json()["modulos"] == ["IND"]
    assert "password" not in r.text and "hash" not in r.text
    a = client.get(f"/api/v1/admin/users/{target}/activity", headers=bearer(tok))
    assert a.status_code == 200 and a.json()["intentos_fallidos"] == 1
    assert a.json()["sesion_activa"] is False

    actions = [x[0] for x in owner.execute(
        "SELECT accion FROM audit.evento WHERE actor_id = %s AND entidad_id = %s ORDER BY seq",
        (admin, str(target))).fetchall()]
    assert actions == ["USR_VIEWED", "USR_ACTIVITY_VIEWED"]
    assert client.get(f"/api/v1/admin/users/{uuid.uuid4()}",
                      headers=bearer(tok)).status_code == 404


def test_org_catalogs_and_area_filter(client, owner):
    _, red = make_admin(owner)
    tok = token(client, red)
    g = owner.execute("INSERT INTO app.gerencia (codigo, nombre) VALUES (%s, 'G prueba') "
                      "RETURNING id", (f"G-{uuid.uuid4().hex[:6]}",)).fetchone()[0]
    owner.execute("INSERT INTO app.area (codigo, nombre, gerencia_id) VALUES (%s, 'A', %s)",
                  (f"A-{uuid.uuid4().hex[:6]}", g))
    areas = client.get("/api/v1/admin/org/areas", params={"management_id": str(g)},
                       headers=bearer(tok)).json()
    assert len(areas) == 1 and areas[0]["gerencia_id"] == str(g)
    # Consistencia gerencia ↔ área en BD.
    import psycopg

    other_g = owner.execute("INSERT INTO app.gerencia (codigo, nombre) VALUES (%s, 'G2') "
                            "RETURNING id", (f"G-{uuid.uuid4().hex[:6]}",)).fetchone()[0]
    uid, _ = make_user(owner)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        owner.execute("UPDATE app.usuario SET gerencia_id=%s, area_id=%s WHERE id=%s",
                      (other_g, areas[0]["id"], uid))
