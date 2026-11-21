"""Integración Fase 6: aprobar (incl. autoaprobación), rechazar, cancelar y aplicar."""

import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from tests.integration.helpers import (
    alta_body,
    bearer,
    ensure_profile,
    login,
    make_admin,
    make_org,
    make_user,
    token,
)

pytestmark = pytest.mark.integration
S = get_settings()
A = "/api/v1/admin"
NEW_PWD = "Definitiva#2026xy"


@pytest.fixture
def client():
    with TestClient(create_app(), base_url="https://testserver",
                    raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def admin(client, owner):
    uid, red = make_admin(owner)
    return uid, bearer(token(client, red))


@pytest.fixture
def org(owner):
    ensure_profile(owner, "PRUEBA_FUNCIONAL")
    return make_org(owner)


def approve(client, h, rid, **body):
    return client.post(f"{A}/requests/{rid}/approve", headers=h, json=body or None)


def req_state(owner, rid) -> str:
    return owner.execute("SELECT estado FROM app.solicitud WHERE id = %s", (rid,)).fetchone()[0]


def user_state(owner, uid) -> str:
    return owner.execute("SELECT estado FROM app.usuario WHERE id = %s", (uid,)).fetchone()[0]


# --------------------------------------------------------------------------- §1-2 autoaprobación

def test_self_approval_of_user_creation_full_flow(client, owner, admin, org, caplog):
    caplog.set_level(logging.DEBUG)
    admin_id, h = admin
    body = alta_body(org)
    created = client.post(f"{A}/users", headers=h, json=body).json()
    rid, uid = created["solicitud_id"], created["usuario_id"]

    r = approve(client, h, rid)  # el mismo administrador que la creó
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "APROBADA" and r.headers["cache-control"] == "no-store"
    temp = r.json()["contrasena_temporal"]
    assert user_state(owner, uid) == "ACTIVO"

    ev = owner.execute("SELECT detalle FROM audit.evento WHERE accion = 'APR_APPROVED' "
                       "AND entidad_id = %s", (rid,)).fetchone()[0]
    assert ev["autoaprobacion"] is True and ev["solicitante"] == ev["aprobador"] == str(admin_id)
    dump = json.dumps(owner.execute("SELECT valor_anterior, valor_nuevo, detalle FROM audit.evento "
                                    "WHERE solicitud_id = %s", (rid,)).fetchall(), default=str)
    assert temp not in dump and temp not in caplog.text
    assert temp not in owner.execute("SELECT password_hash FROM app.credencial WHERE "
                                     "usuario_id = %s", (uid,)).fetchone()[0]

    # Sin doble aprobación: ningún estado intermedio existe en el modelo.
    chk = owner.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = "
                        "'app.solicitud'::regclass AND contype = 'c'").fetchall()
    assert not any(w in str(chk).upper() for w in ("SEGUNDA", "PARCIAL", "ESPERA"))

    # El usuario inicia sesión con la temporal, la cambia y ve sus módulos.
    red = body["usuario_red"].lower()
    t = login(client, red, temp).json()
    assert t["debe_cambiar_contrasena"] is True
    client.post("/api/v1/auth/password/change", headers=bearer(t["access_token"]),
                json={"current_password": temp, "new_password": NEW_PWD})
    mods = client.get("/api/v1/me/modules", headers=bearer(token(client, red, NEW_PWD))).json()
    assert [m["codigo"] for m in mods["modulos"]] == ["IND"]

    # Una solicitud resuelta no se vuelve a resolver.
    again = approve(client, h, rid)
    assert again.status_code == 409 and again.json()["error"]["code"] == "REQUEST_ALREADY_RESOLVED"
    assert client.post(f"{A}/requests/{rid}/reject", headers=h,
                       json={"motivo": "Ya no corresponde"}).status_code == 409

    hist = client.get(f"{A}/users/{uid}/history", headers=h).json()
    assert [(e["estado_anterior"], e["estado_nuevo"]) for e in hist["estados"]] == [
        ("PENDIENTE_ALTA", "ACTIVO")]
    assert hist["solicitudes"][0]["estado"] == "APROBADA"


def test_any_of_the_two_admins_can_approve(client, owner, admin):
    _, h1 = admin
    _, red2 = make_user(owner, perfil="ADMINISTRADOR", modulos=("ADM",))  # 2.º administrador
    h2 = bearer(token(client, red2))
    uid, _ = make_user(owner)
    rid = client.patch(f"{A}/users/{uid}", headers=h1,
                       json={"correo": "otro@example.org"}).json()["solicitud_id"]
    r = approve(client, h2, rid, comentario="Verificado con el área")
    assert r.status_code == 200
    ev = owner.execute("SELECT detalle FROM audit.evento WHERE accion = 'APR_APPROVED' "
                       "AND entidad_id = %s", (rid,)).fetchone()[0]
    assert ev["autoaprobacion"] is False


# --------------------------------------------------------------------------- §3 modificación

def test_grouped_modification_all_or_nothing_and_linked_correction(client, owner, admin, org):
    _, h = admin
    uid, _ = make_user(owner)
    rid = client.patch(f"{A}/users/{uid}", headers=h, json={
        "correo": "c1@example.org", "primer_apellido": "Gómez"}).json()["solicitud_id"]

    owner.execute("UPDATE app.usuario SET correo = 'cambiado@x.co' WHERE id = %s", (uid,))
    r = approve(client, h, rid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "SNAPSHOT_MISMATCH"
    assert owner.execute("SELECT primer_apellido FROM app.usuario WHERE id = %s",
                         (uid,)).fetchone()[0] == "User"  # nada aplicado
    assert req_state(owner, rid) == "PENDIENTE"

    assert client.post(f"{A}/requests/{rid}/cancel", headers=h,
                       json={"motivo": "corto"}).status_code == 422
    assert client.post(f"{A}/requests/{rid}/cancel", headers=h,
                       json={"motivo": "El correo cambió; se rehace"}).json()["estado"] == \
        "CANCELADA"
    r2 = client.patch(f"{A}/users/{uid}", headers=h, json={
        "correo": "c1@example.org", "primer_apellido": "Gómez",
        **{k: org[k] for k in ("gerencia_id", "area_id", "cargo_id")},
        "solicitud_vinculada_id": rid})
    assert r2.status_code == 202
    assert approve(client, h, r2.json()["solicitud_id"]).status_code == 200
    row = owner.execute("SELECT correo, primer_apellido, gerencia_id::text FROM app.usuario "
                        "WHERE id = %s", (uid,)).fetchone()
    assert row == ("c1@example.org", "Gómez", org["gerencia_id"])

    hist = client.get(f"{A}/users/{uid}/history", headers=h).json()["solicitudes"]
    assert [s["estado"] for s in hist] == ["CANCELADA", "APROBADA"]
    assert hist[1]["solicitud_vinculada"] == hist[0]["numero"]
    attrs = {i["atributo"]: (i["valor_anterior"], i["valor_nuevo"]) for i in hist[1]["items"]}
    assert attrs["correo"] == ("cambiado@x.co", "c1@example.org")


def test_invalid_links(client, owner, admin):
    _, h = admin
    u1, _ = make_user(owner)
    u2, _ = make_user(owner)
    pending = client.patch(f"{A}/users/{u1}", headers=h,
                           json={"correo": "p@example.org"}).json()["solicitud_id"]
    r = client.patch(f"{A}/users/{u2}", headers=h,
                     json={"correo": "q@example.org", "solicitud_vinculada_id": pending})
    assert r.status_code == 422  # de otra entidad
    client.post(f"{A}/requests/{pending}/cancel", headers=h, json={"motivo": "Se reemplaza aquí"})
    pending2 = client.patch(f"{A}/users/{u1}", headers=h,
                            json={"correo": "r@example.org"}).json()["solicitud_id"]
    client.post(f"{A}/requests/{pending2}/cancel", headers=h, json={"motivo": "Otro reemplazo"})
    ok = client.patch(f"{A}/users/{u1}", headers=h,
                      json={"correo": "s@example.org", "solicitud_vinculada_id": pending})
    assert ok.status_code == 202
    bad = client.post(f"{A}/users/{u2}/deactivate", headers=h, json={
        "motivo": "Vinculación a pendiente", "solicitud_vinculada_id": ok.json()["solicitud_id"]})
    assert bad.status_code == 422


# --------------------------------------------------------------------------- módulos

def test_modules_request_applies_exact_set_keeping_history(client, owner, admin):
    _, h = admin
    uid, red = make_user(owner, modulos=("IND",))
    rid = client.put(f"{A}/users/{uid}/modules", headers=h,
                     json={"modulos": ["ADM", "IND"]}).json()["solicitud_id"]
    assert approve(client, h, rid).status_code == 200
    rid = client.put(f"{A}/users/{uid}/modules", headers=h,
                     json={"modulos": []}).json()["solicitud_id"]
    assert approve(client, h, rid).status_code == 200
    rows = owner.execute("SELECT m.codigo, um.estado FROM app.usuario_modulo um JOIN app.modulo m "
                         "ON m.id = um.modulo_id WHERE um.usuario_id = %s ORDER BY 1",
                         (uid,)).fetchall()
    assert rows == [("ADM", "INACTIVO"), ("IND", "INACTIVO")]  # historia conservada
    mods = client.get("/api/v1/me/modules", headers=bearer(token(client, red))).json()
    assert mods["modulos"] == [] and mods["mensaje"]


# ---------------------------------------------------------------- §4-5 inhabilitar/reactivar

def test_deactivation_cuts_session_and_reactivation_requires_new_password(client, owner, admin):
    _, h = admin
    uid, red = make_user(owner)
    user_tok = token(client, red)
    rid = client.post(f"{A}/users/{uid}/deactivate", headers=h,
                      json={"motivo": "Retiro de la organización"}).json()["solicitud_id"]
    assert client.get("/api/v1/me", headers=bearer(user_tok)).status_code == 200  # aún no
    assert approve(client, h, rid).status_code == 200
    assert client.get("/api/v1/me", headers=bearer(user_tok)).status_code == 401
    assert user_state(owner, uid) == "INACTIVO"
    assert owner.execute("SELECT motivo_fin FROM app.sesion WHERE usuario_id = %s",
                         (uid,)).fetchone()[0] == "INHABILITACION"
    assert login(client, red).status_code == 401

    rid = client.post(f"{A}/users/{uid}/reactivate", headers=h,
                      json={"motivo": "Reingreso del funcionario"}).json()["solicitud_id"]
    temp = approve(client, h, rid).json()["contrasena_temporal"]
    assert login(client, red).status_code == 401  # la contraseña anterior ya no sirve
    assert login(client, red, temp).json()["debe_cambiar_contrasena"] is True

    estados = client.get(f"{A}/users/{uid}/history", headers=h).json()["estados"]
    assert [(e["estado_nuevo"], e["motivo"]) for e in estados] == [
        ("INACTIVO", "Retiro de la organización"), ("ACTIVO", "Reingreso del funcionario")]


def test_cannot_leave_system_without_admins_at_approval(client, owner, admin):
    a1, h1 = admin
    a2, red2 = make_user(owner, perfil="ADMINISTRADOR", modulos=("ADM",))
    rid = client.post(f"{A}/users/{a2}/deactivate", headers=h1,
                      json={"motivo": "Rotación de administrador"}).json()["solicitud_id"]
    owner.execute("UPDATE app.usuario SET estado = 'INACTIVO' WHERE id = %s", (a1,))
    r = approve(client, bearer(token(client, red2)), rid)
    assert r.status_code == 409 and req_state(owner, rid) == "PENDIENTE"


def test_admin_limit_enforced_at_approval(client, owner, admin, org):
    _, h = admin
    make_user(owner, perfil="ADMINISTRADOR", modulos=("ADM",))  # ya hay 2 activos
    created = client.post(f"{A}/users", headers=h,
                          json=alta_body(org, perfil="ADMINISTRADOR", modulos=["ADM"])).json()
    r = approve(client, h, created["solicitud_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "ADMIN_LIMIT"
    assert req_state(owner, created["solicitud_id"]) == "PENDIENTE"
    assert user_state(owner, created["usuario_id"]) == "PENDIENTE_ALTA"
    assert owner.execute("SELECT count(*) FROM app.credencial WHERE usuario_id = %s",
                         (created["usuario_id"],)).fetchone()[0] == 0


# ---------------------------------------------------------------- §6-7 rechazo y corrección

def test_rejected_creation_and_linked_correction_reuses_record(client, owner, admin, org):
    _, h = admin
    body = alta_body(org)
    created = client.post(f"{A}/users", headers=h, json=body).json()
    assert client.post(f"{A}/requests/{created['solicitud_id']}/reject", headers=h,
                       json={}).status_code == 422
    r = client.post(f"{A}/requests/{created['solicitud_id']}/reject", headers=h,
                    json={"motivo": "Apellido mal escrito"})
    assert r.json()["estado"] == "RECHAZADA"
    assert user_state(owner, created["usuario_id"]) == "INACTIVO"
    assert login(client, body["usuario_red"]).status_code == 401

    # Reactivar un alta que nunca se activó no procede.
    rr = client.post(f"{A}/users/{created['usuario_id']}/reactivate", headers=h,
                     json={"motivo": "Intento de reactivar alta"}).json()["solicitud_id"]
    assert approve(client, h, rr).status_code == 422
    client.post(f"{A}/requests/{rr}/cancel", headers=h, json={"motivo": "No procede reactivar"})

    # Sin vincular: el usuario de red ya existe.
    fixed = {**body, "primer_apellido": "Pereira"}
    assert client.post(f"{A}/users", headers=h, json=fixed).status_code == 409
    linked = client.post(f"{A}/users", headers=h,
                         json={**fixed, "solicitud_vinculada_id": created["solicitud_id"]})
    assert linked.status_code == 202, linked.text
    assert linked.json()["usuario_id"] == created["usuario_id"]  # mismo registro
    assert user_state(owner, created["usuario_id"]) == "PENDIENTE_ALTA"
    assert approve(client, h, linked.json()["solicitud_id"]).status_code == 200
    assert owner.execute("SELECT primer_apellido, estado FROM app.usuario WHERE id = %s",
                         (created["usuario_id"],)).fetchone() == ("Pereira", "ACTIVO")


# --------------------------------------------------------------------------- §8 fail-closed

def test_approval_is_fail_closed(client, owner, admin):
    _, h = admin
    uid, _ = make_user(owner)
    rid = client.patch(f"{A}/users/{uid}", headers=h,
                       json={"correo": "fc@example.org"}).json()["solicitud_id"]
    owner.execute(f'REVOKE INSERT ON audit.evento FROM "{S.app_db_user}"')
    try:
        r = approve(client, h, rid)
    finally:
        owner.execute(f'GRANT INSERT ON audit.evento TO "{S.app_db_user}"')
    assert r.status_code == 503
    assert req_state(owner, rid) == "PENDIENTE"
    assert owner.execute("SELECT correo FROM app.usuario WHERE id = %s",
                         (uid,)).fetchone()[0] == "t@x.co"
    assert approve(client, h, rid).status_code == 200  # recuperado el servicio, se aplica


def test_history_requires_permission_and_404(client, owner, admin):
    _, h = admin
    assert client.get(f"{A}/users/{uuid.uuid4()}/history", headers=h).status_code == 404
    _, red = make_user(owner)
    other, _ = make_user(owner)
    assert client.get(f"{A}/users/{other}/history",
                      headers=bearer(token(client, red))).status_code == 403
