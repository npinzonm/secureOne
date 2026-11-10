"""Integración Fase 3: criterios de aceptación de docs/fases/FASE-3.md (§1–§13)."""

import asyncio
import json
import logging
import secrets
import string
import uuid

import psycopg
import pytest
import redis
import redis.asyncio
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.db import Database
from app.core.ids import uuid7
from app.kernel.audit import IncidentSpool
from app.main import create_app
from app.modules.auth.application.bootstrap import AdminData, BootstrapError, bootstrap_admin
from app.modules.auth.domain.password_policy import password_policy_violations
from app.modules.auth.infrastructure.hashing import hash_password

pytestmark = pytest.mark.integration

S = get_settings()
ROLE = S.app_db_user
PWD = "Inicial#2026abcd"
NEW_PWD = "Nueva#Clave2026x"


# --------------------------------------------------------------------------- utilidades

def rand_red() -> str:
    return "".join(secrets.choice(string.ascii_lowercase) + secrets.choice(string.digits)
                   for _ in range(4))


def make_user(owner, *, password=PWD, must_change=False, estado="ACTIVO") -> tuple[uuid.UUID, str]:
    """Usuario funcional de prueba (perfil no administrativo) creado directamente en BD."""
    owner.execute(
        "INSERT INTO app.perfil (codigo, nombre) VALUES ('PRUEBA_FUNCIONAL', 'Prueba') "
        "ON CONFLICT (codigo) DO NOTHING"
    )
    uid, red = uuid7(), rand_red()
    h = hash_password(password)
    owner.execute(
        "INSERT INTO app.usuario (id, usuario_red, identificacion, nombre, primer_apellido, correo,"
        " perfil_id, estado) SELECT %s, %s, %s, 'Test', 'User', 't@x.co', id, %s "
        "FROM app.perfil WHERE codigo = 'PRUEBA_FUNCIONAL'",
        (uid, red, f"ID-{uuid.uuid4().hex[:10]}", estado),
    )
    owner.execute("INSERT INTO app.credencial (usuario_id, password_hash, debe_cambiar) "
                  "VALUES (%s, %s, %s)", (uid, h, must_change))
    owner.execute("INSERT INTO app.historial_contrasena (id, usuario_id, password_hash) "
                  "VALUES (%s, %s, %s)", (uuid7(), uid, h))
    return uid, red


def login(c: TestClient, red: str, password: str = PWD):
    return c.post("/api/v1/auth/login", json={"usuario_red": red, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def session_row(owner, uid):
    return owner.execute(
        "SELECT id, finalizada_en, motivo_fin FROM app.sesion WHERE usuario_id = %s "
        "ORDER BY iniciada_en DESC LIMIT 1", (uid,)
    ).fetchone()


def audit_actions(owner, uid) -> list[str]:
    return [r[0] for r in owner.execute(
        "SELECT accion FROM audit.evento WHERE actor_id = %s OR entidad_id = %s ORDER BY seq",
        (uid, str(uid)),
    ).fetchall()]


@pytest.fixture
def client():
    with TestClient(create_app(), base_url="https://testserver",
                    raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def rds():
    r = redis.Redis(host=S.redis_host, port=S.redis_port,
                    password=S.redis_password.get_secret_value())
    yield r
    r.close()


# --------------------------------------------------------------------------- §1 bootstrap

def test_bootstrap_two_admins_max_and_db_guard(owner):
    owner.execute("UPDATE app.usuario SET estado = 'INACTIVO' WHERE perfil_id = "
                  "(SELECT id FROM app.perfil WHERE codigo = 'ADMINISTRADOR')")

    async def run():
        db = Database(S.sqlalchemy_url, pool_size=1, max_overflow=0)
        spool = IncidentSpool(S.spool_dir)
        try:
            temps = []
            for _ in range(2):
                temps.append(await bootstrap_admin(S, db.sessionmaker, spool, AdminData(
                    usuario_red=rand_red().upper(), identificacion=uuid.uuid4().hex[:12],
                    nombre="Admin", primer_apellido="Uno", correo="admin@example.org")))
            with pytest.raises(BootstrapError, match="dos administradores"):
                await bootstrap_admin(S, db.sessionmaker, spool, AdminData(
                    usuario_red=rand_red(), identificacion=uuid.uuid4().hex[:12],
                    nombre="Admin", primer_apellido="Tres", correo="admin3@example.org"))
            return temps
        finally:
            await db.dispose()

    temps = asyncio.run(run())
    assert all(password_policy_violations(t, "") == [] for t in temps)
    rows = owner.execute(
        "SELECT u.usuario_red, c.debe_cambiar, c.password_hash FROM app.usuario u "
        "JOIN app.credencial c ON c.usuario_id = u.id JOIN app.perfil p ON p.id = u.perfil_id "
        "WHERE p.codigo = 'ADMINISTRADOR' AND u.estado = 'ACTIVO'"
    ).fetchall()
    assert len(rows) == 2
    assert all(r[0] == r[0].lower() and r[1] is True and r[2].startswith("$argon2id$")
               for r in rows)
    ev = owner.execute("SELECT valor_nuevo::text FROM audit.evento WHERE accion = 'AUTH_BOOTSTRAP' "
                       "ORDER BY seq DESC LIMIT 2").fetchall()
    assert len(ev) == 2 and all(t not in e[0] for e in ev for t in temps)

    # Guarda de BD: ni siquiera el owner inserta un 3.er administrador activo.
    with pytest.raises(psycopg.errors.CheckViolation, match="dos administradores"):
        owner.execute(
            "INSERT INTO app.usuario (id, usuario_red, identificacion, nombre, primer_apellido,"
            " correo, perfil_id, estado) SELECT %s, %s, %s, 'X', 'Y', 'x@y.co', id, 'ACTIVO' "
            "FROM app.perfil WHERE codigo = 'ADMINISTRADOR'",
            (uuid7(), rand_red(), uuid.uuid4().hex[:12]),
        )


# --------------------------------------------------------------------------- §2-§3 cambio

def test_must_change_flow_and_policy(client, owner):
    uid, red = make_user(owner, must_change=True)
    r = login(client, red.upper())
    assert r.status_code == 200 and r.json()["debe_cambiar_contrasena"] is True
    assert "so_refresh" not in r.cookies  # sin refresh mientras deba cambiarla
    tok = r.json()["access_token"]

    me = client.get("/api/v1/me", headers=bearer(tok))
    assert me.status_code == 403 and me.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.get("/api/v1/auth/session", headers=bearer(tok)).json()["restringida"] is True

    def change(current, new):
        return client.post("/api/v1/auth/password/change", headers=bearer(tok),
                           json={"current_password": current, "new_password": new})

    bad_current = change("Mala#Actual2026", NEW_PWD)
    assert bad_current.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"
    for bad, code in [("Corta#1a", "MIN_LENGTH"), ("sinmayuscula#2026", "UPPERCASE_REQUIRED"),
                      (f"X#9{red}abc", "CONTAINS_USERNAME"), (PWD, "REUSED_PASSWORD")]:
        r = change(PWD, bad)
        assert r.status_code == 422, bad
        assert code in r.json()["error"]["details"]["violations"]

    assert change(PWD, NEW_PWD).status_code == 204
    assert client.get("/api/v1/auth/session", headers=bearer(tok)).status_code == 401
    assert session_row(owner, uid)[2] == "CAMBIO_CONTRASENA"

    r = login(client, red, NEW_PWD)
    assert r.status_code == 200 and r.json()["debe_cambiar_contrasena"] is False
    me = client.get("/api/v1/me", headers=bearer(r.json()["access_token"]))
    assert me.status_code == 200 and me.json()["usuario_red"] == red
    assert "password" not in me.text and "hash" not in me.text
    assert owner.execute("SELECT count(*) FROM app.historial_contrasena WHERE usuario_id = %s",
                         (uid,)).fetchone()[0] == 2
    assert "AUTH_PASSWORD_CHANGED" in audit_actions(owner, uid)


def test_password_history_blocks_last_five(client, owner):
    uid, red = make_user(owner)
    pwds = [PWD] + [f"Rotacion#{i}2026ab" for i in range(1, 6)]
    for prev, new in zip(pwds, pwds[1:], strict=False):
        tok = login(client, red, prev).json()["access_token"]
        assert client.post("/api/v1/auth/password/change", headers=bearer(tok),
                           json={"current_password": prev, "new_password": new}).status_code == 204
    tok = login(client, red, pwds[-1]).json()["access_token"]
    # pwds[1] es la 5.ª más reciente (incluida la actual) → bloqueada; PWD (6.ª) ya se permite.
    r = client.post("/api/v1/auth/password/change", headers=bearer(tok),
                    json={"current_password": pwds[-1], "new_password": pwds[1]})
    assert "REUSED_PASSWORD" in r.json()["error"]["details"]["violations"]
    r = client.post("/api/v1/auth/password/change", headers=bearer(tok),
                    json={"current_password": pwds[-1], "new_password": PWD})
    assert r.status_code == 204
    assert owner.execute("SELECT count(*) FROM app.historial_contrasena WHERE usuario_id = %s",
                         (uid,)).fetchone()[0] == 5


# --------------------------------------------------------------------------- §4 mensajes genéricos

def test_generic_message_for_unknown_wrong_inactive_pending(client, owner):
    _, active = make_user(owner)
    _, inactive = make_user(owner, estado="INACTIVO")
    _, pending = make_user(owner, estado="PENDIENTE_ALTA")
    bodies = [
        login(client, "z9z9z9z9"),
        login(client, active, "Equivocada#2026"),
        login(client, inactive),
        login(client, pending),
    ]
    assert {r.status_code for r in bodies} == {401}
    assert {r.json()["error"]["message"] for r in bodies} == {"Usuario o contraseña inválidos."}
    assert {r.json()["error"]["code"] for r in bodies} == {"INVALID_CREDENTIALS"}


# --------------------------------------------------------------------------- §5 bloqueo

def test_lockout_on_fifth_attempt_and_auto_unlock(client, owner):
    uid, red = make_user(owner)
    for _ in range(4):
        assert login(client, red, "Equivocada#2026").status_code == 401
    assert owner.execute("SELECT intentos_fallidos FROM app.credencial WHERE usuario_id = %s",
                         (uid,)).fetchone()[0] == 4
    r = login(client, red, "Equivocada#2026")
    assert r.status_code == 423 and r.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert "minut" not in r.json()["error"]["message"].lower()  # PD-17: sin indicar minutos
    assert login(client, red).status_code == 423                # ni con la contraseña correcta
    estado, mins = owner.execute(
        "SELECT u.estado, extract(epoch FROM c.bloqueado_hasta - now()) / 60 FROM app.usuario u "
        "JOIN app.credencial c ON c.usuario_id = u.id WHERE u.id = %s", (uid,)).fetchone()
    assert estado == "ACTIVO" and 14 < float(mins) <= 15
    assert "AUTH_LOCKOUT" in audit_actions(owner, uid)

    # Simula el paso de 15 minutos.
    owner.execute("UPDATE app.credencial SET bloqueado_hasta = now() - interval '1 second' "
                  "WHERE usuario_id = %s", (uid,))
    assert login(client, red).status_code == 200
    assert owner.execute("SELECT intentos_fallidos, bloqueado_hasta FROM app.credencial "
                         "WHERE usuario_id = %s", (uid,)).fetchone() == (0, None)


# --------------------------------------------------------------------------- §6 una sesión

def test_new_login_invalidates_previous_session(client, owner):
    uid, red = make_user(owner)
    t1 = login(client, red).json()["access_token"]
    first_sid = session_row(owner, uid)[0]
    t2 = login(client, red).json()["access_token"]
    r = client.get("/api/v1/me", headers=bearer(t1))
    assert r.status_code == 401 and r.json()["error"]["code"] == "SESSION_ENDED"
    assert client.get("/api/v1/me", headers=bearer(t2)).status_code == 200
    assert owner.execute("SELECT motivo_fin FROM app.sesion WHERE id = %s",
                         (first_sid,)).fetchone()[0] == "REEMPLAZADA"
    assert owner.execute("SELECT count(*) FROM app.sesion WHERE usuario_id = %s AND "
                         "finalizada_en IS NULL", (uid,)).fetchone()[0] == 1
    assert "AUTH_SESSION_REPLACED" in audit_actions(owner, uid)


# --------------------------------------------------------------------------- §7 inactividad

def test_inactivity_sliding_window_and_expiry(client, owner, rds):
    uid, red = make_user(owner)
    tok = login(client, red).json()["access_token"]
    sid = session_row(owner, uid)[0]
    key = f"so:sess:{sid}"
    assert 890 <= rds.ttl(key) <= 900

    rds.expire(key, 100)
    # Consultar el estado NO cuenta como actividad.
    assert client.get("/api/v1/auth/session", headers=bearer(tok)).json()[
        "segundos_restantes_inactividad"] <= 100
    assert rds.ttl(key) <= 100
    # Una petición real sí renueva la ventana.
    assert client.get("/api/v1/me", headers=bearer(tok)).status_code == 200
    assert rds.ttl(key) > 800

    rds.delete(key)  # equivale a 15 min sin actividad
    assert client.get("/api/v1/me", headers=bearer(tok)).status_code == 401
    assert session_row(owner, uid)[2] == "INACTIVIDAD"
    assert "AUTH_SESSION_EXPIRED" in audit_actions(owner, uid)


# --------------------------------------------------------------------------- §8 refresh

def test_refresh_rotation_and_reuse_detection(client, owner):
    uid, red = make_user(owner)
    r = login(client, red)
    first_refresh = r.cookies["so_refresh"]
    r2 = client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200
    second_refresh = r2.cookies["so_refresh"]
    assert second_refresh != first_refresh
    new_tok = r2.json()["access_token"]
    assert client.get("/api/v1/me", headers=bearer(new_tok)).status_code == 200

    # Reutilizar el refresh ya usado → se revoca toda la sesión.
    client.cookies.clear()
    reuse = client.post("/api/v1/auth/refresh", headers={"Cookie": f"so_refresh={first_refresh}"})
    assert reuse.status_code == 401
    assert session_row(owner, uid)[2] == "REUSO_REFRESH"
    assert client.get("/api/v1/me", headers=bearer(new_tok)).status_code == 401
    ok_after = client.post("/api/v1/auth/refresh",
                           headers={"Cookie": f"so_refresh={second_refresh}"})
    assert ok_after.status_code == 401
    assert "AUTH_REFRESH_REUSE" in audit_actions(owner, uid)
    assert owner.execute(
        "SELECT count(*) FROM app.refresh_token rt JOIN app.sesion s ON s.id = rt.sesion_id "
        "WHERE s.usuario_id = %s AND rt.revocado_en IS NULL", (uid,)).fetchone()[0] == 0


def test_refresh_cookie_attributes(client, owner):
    _, red = make_user(owner)
    set_cookie = login(client, red).headers["set-cookie"].lower()
    for attr in ("httponly", "samesite=strict", "path=/api/v1/auth", "secure"):
        assert attr in set_cookie


# --------------------------------------------------------------------------- §9 logout

def test_logout_invalidates_token_and_refresh(client, owner):
    uid, red = make_user(owner)
    r = login(client, red)
    tok, refresh_raw = r.json()["access_token"], r.cookies["so_refresh"]
    assert client.post("/api/v1/auth/logout", headers=bearer(tok)).status_code == 204
    assert client.get("/api/v1/me", headers=bearer(tok)).status_code == 401
    client.cookies.clear()
    assert client.post("/api/v1/auth/refresh",
                       headers={"Cookie": f"so_refresh={refresh_raw}"}).status_code == 401
    assert owner.execute("SELECT motivo_fin FROM app.sesion WHERE usuario_id = %s ORDER BY "
                         "iniciada_en LIMIT 1", (uid,)).fetchone()[0] == "LOGOUT"
    assert "AUTH_LOGOUT" in audit_actions(owner, uid)


# --------------------------------------------------------------------------- §10 inactivación

def test_deactivated_user_with_valid_token_is_rejected(client, owner):
    uid, red = make_user(owner)
    tok = login(client, red).json()["access_token"]
    owner.execute("UPDATE app.usuario SET estado = 'INACTIVO' WHERE id = %s", (uid,))
    assert client.get("/api/v1/me", headers=bearer(tok)).status_code == 401
    assert session_row(owner, uid)[2] == "INHABILITACION"


def test_missing_or_malformed_token(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=bearer("no.es.jwt")).status_code == 401


# --------------------------------------------------------------------------- §11 auditoría caída

def test_login_fail_closed_when_audit_unavailable(client, owner, rds):
    uid, red = make_user(owner)
    owner.execute(f'REVOKE INSERT ON audit.evento FROM "{ROLE}"')
    try:
        r = login(client, red)
    finally:
        owner.execute(f'GRANT INSERT ON audit.evento TO "{ROLE}"')
    assert r.status_code == 503 and r.json()["error"]["code"] == "AUDIT_UNAVAILABLE"
    assert "access_token" not in r.text
    assert owner.execute("SELECT count(*) FROM app.sesion WHERE usuario_id = %s",
                         (uid,)).fetchone()[0] == 0
    assert rds.get(f"so:usess:{uid}") is None  # Redis limpio
    # Recuperado el servicio, el login funciona.
    assert login(client, red).status_code == 200


# --------------------------------------------------------------------------- §12 Redis caído

def test_redis_unavailable_returns_503(client, owner):
    _, red = make_user(owner)
    tok = login(client, red).json()["access_token"]
    store = client.app.state.auth.store
    original = store.client
    store.client = redis.asyncio.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.5)
    try:
        assert login(client, red).status_code == 503
        assert client.get("/api/v1/me", headers=bearer(tok)).status_code == 503
    finally:
        store.client = original


# --------------------------------------------------------------------------- §13 secretos

def test_no_secrets_in_logs_audit_or_responses(client, owner, caplog):
    caplog.set_level(logging.DEBUG)
    uid, red = make_user(owner, must_change=True)
    r = login(client, red)
    tok = r.json()["access_token"]
    client.post("/api/v1/auth/password/change", headers=bearer(tok),
                json={"current_password": PWD, "new_password": NEW_PWD})
    r2 = login(client, red, NEW_PWD)
    login(client, red, "Equivocada#2026")
    refresh_raw = r2.cookies["so_refresh"]
    logs = caplog.text
    audit = json.dumps(owner.execute(
        "SELECT valor_anterior, valor_nuevo, detalle FROM audit.evento "
        "WHERE actor_id = %s OR entidad_id = %s", (uid, str(uid))).fetchall(), default=str)
    for secret in (PWD, NEW_PWD, "Equivocada#2026", tok, refresh_raw, "$argon2id$"):
        assert secret not in logs
        assert secret not in audit
