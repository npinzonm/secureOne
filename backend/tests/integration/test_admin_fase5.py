"""Integración Fase 5: operaciones directas y creación de solicitudes (docs/fases/FASE-5.md)."""

import json
import logging
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from tests.integration.helpers import (
    bearer,
    ensure_profile,
    ensure_role,
    login,
    make_admin,
    make_user,
    rand_red,
    token,
)

pytestmark = pytest.mark.integration
S = get_settings()
A = "/api/v1/admin"


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
    """Catálogos org de prueba (en el sistema real solo llegan desde TH)."""
    sfx = uuid.uuid4().hex[:6]
    g = owner.execute("INSERT INTO app.gerencia (codigo, nombre) VALUES (%s, 'G') RETURNING id",
                      (f"G{sfx}",)).fetchone()[0]
    g2 = owner.execute("INSERT INTO app.gerencia (codigo, nombre) VALUES (%s, 'G2') RETURNING id",
                       (f"H{sfx}",)).fetchone()[0]
    a = owner.execute("INSERT INTO app.area (codigo, nombre, gerencia_id) VALUES (%s, 'A', %s) "
                      "RETURNING id", (f"A{sfx}", g)).fetchone()[0]
    c = owner.execute("INSERT INTO app.cargo (codigo_cargo, nombre) VALUES (%s, 'C') RETURNING id",
                      (int(uuid.uuid4().int % 10**8) + 1,)).fetchone()[0]
    return {"gerencia_id": str(g), "area_id": str(a), "cargo_id": str(c), "otra_gerencia": str(g2)}


def events(owner, accion: str, entidad_id: str | None = None) -> list:
    q = "SELECT valor_anterior, valor_nuevo, detalle FROM audit.evento WHERE accion = %s"
    params: tuple = (accion,)
    if entidad_id:
        q += " AND entidad_id = %s"
        params += (entidad_id,)
    return owner.execute(q + " ORDER BY seq", params).fetchall()


# =========================================================================== directas: usuarios

def test_password_reset(client, owner, admin, caplog):
    caplog.set_level(logging.DEBUG)
    _, h = admin
    uid, red = make_user(owner)
    user_tok = token(client, red)
    for _ in range(5):
        login(client, red, "Equivocada#2026")  # cuenta bloqueada

    r = client.post(f"{A}/users/{uid}/password-reset", headers=h)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    temp = r.json()["contrasena_temporal"]
    assert client.get("/api/v1/me", headers=bearer(user_tok)).status_code == 401
    row = owner.execute("SELECT debe_cambiar, intentos_fallidos, bloqueado_hasta, password_hash "
                        "FROM app.credencial WHERE usuario_id = %s", (uid,)).fetchone()
    assert row[:3] == (True, 0, None) and temp not in row[3]
    lr = login(client, red, temp)
    assert lr.status_code == 200 and lr.json()["debe_cambiar_contrasena"] is True

    dump = json.dumps(owner.execute("SELECT valor_anterior, valor_nuevo, detalle FROM audit.evento "
                                    "WHERE entidad_id = %s", (str(uid),)).fetchall(), default=str)
    assert temp not in dump and temp not in caplog.text
    assert events(owner, "AUTH_PASSWORD_RESET", str(uid))

    inactive, _ = make_user(owner, estado="INACTIVO")
    assert client.post(f"{A}/users/{inactive}/password-reset", headers=h).status_code == 422
    assert client.post(f"{A}/users/{admin[0]}/password-reset", headers=h).status_code == 422


def test_revoke_session(client, owner, admin):
    _, h = admin
    uid, red = make_user(owner)
    tok = token(client, red)
    assert client.post(f"{A}/users/{uid}/sessions/revoke", headers=h).json() == {"revocada": True}
    assert client.get("/api/v1/me", headers=bearer(tok)).status_code == 401
    assert owner.execute("SELECT motivo_fin FROM app.sesion WHERE usuario_id = %s",
                         (uid,)).fetchone()[0] == "REVOCADA_ADMIN"
    assert client.post(f"{A}/users/{uid}/sessions/revoke", headers=h).json() == {"revocada": False}


# =========================================================================== directas: IAM

def test_profiles_crud_rules_and_protection(client, owner, admin):
    _, h = admin
    code = f"ZP_{uuid.uuid4().hex[:6].upper()}"
    r = client.post(f"{A}/profiles", headers=h, json={"codigo": code, "nombre": "Perfil Z"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.post(f"{A}/profiles", headers=h,
                       json={"codigo": code, "nombre": "x"}).status_code == 409
    assert client.post(f"{A}/profiles", headers=h,
                       json={"codigo": "minus", "nombre": "x"}).status_code == 422
    r = client.patch(f"{A}/profiles/{pid}", headers=h, json={"nombre": "Perfil Z2"})
    assert r.status_code == 200 and r.json()["nombre"] == "Perfil Z2"
    ev = events(owner, "IAM_PROFILE_UPDATED", pid)[-1]
    assert ev[0]["nombre"] == "Perfil Z" and ev[1]["nombre"] == "Perfil Z2"

    make_user(owner, perfil=code)
    r = client.post(f"{A}/profiles/{pid}/status", headers=h, json={"estado": "INACTIVO"})
    assert r.status_code == 409 and len(r.json()["error"]["details"]["usuarios_activos"]) == 1

    empty = client.post(f"{A}/profiles", headers=h,
                        json={"codigo": code + "_B", "nombre": "B"}).json()["id"]
    assert client.post(f"{A}/profiles/{empty}/status", headers=h,
                       json={"estado": "INACTIVO"}).status_code == 200
    assert owner.execute("SELECT estado FROM app.perfil WHERE id = %s",
                         (empty,)).fetchone()[0] == "INACTIVO"  # lógico, no borrado

    adm = owner.execute("SELECT id FROM app.perfil WHERE codigo='ADMINISTRADOR'").fetchone()[0]
    assert client.patch(f"{A}/profiles/{adm}", headers=h, json={"nombre": "x"}).status_code == 409
    assert client.post(f"{A}/profiles/{adm}/status", headers=h,
                       json={"estado": "INACTIVO"}).status_code == 409
    assert client.post(f"{A}/profiles/{adm}/roles/impact", headers=h,
                       json={"codigos": []}).status_code == 409


def test_role_permissions_require_confirmed_impact(client, owner, admin):
    _, h = admin
    rcode = f"ZR_{uuid.uuid4().hex[:6].upper()}"
    rid = client.post(f"{A}/roles", headers=h, json={"codigo": rcode, "nombre": "R"}).json()["id"]
    pcode = f"ZPR_{uuid.uuid4().hex[:6].upper()}"
    ensure_profile(owner, pcode, (rcode,))
    make_user(owner, perfil=pcode)
    want = {"codigos": ["ADM.PERFIL.CONSULTA", "ADM.ROL.CONSULTA"]}

    r = client.put(f"{A}/roles/{rid}/permissions", headers=h, json=want)
    assert r.status_code == 422 and r.json()["error"]["code"] == "IMPACT_CONFIRMATION_REQUIRED"

    imp = client.post(f"{A}/roles/{rid}/permissions/impact", headers=h, json=want).json()
    assert imp["perfiles_afectados"] == [pcode] and imp["usuarios_afectados"] == 1
    assert imp["agregados"] == want["codigos"] and imp["quitados"] == []

    make_user(owner, perfil=pcode)  # el impacto cambia entre consulta y confirmación
    r = client.put(f"{A}/roles/{rid}/permissions", headers=h,
                   json={**want, "confirm_impact_token": imp["confirm_impact_token"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "IMPACT_CHANGED"

    tok = client.post(f"{A}/roles/{rid}/permissions/impact", headers=h,
                      json=want).json()["confirm_impact_token"]
    other = {"codigos": ["ADM.PERFIL.CONSULTA"], "confirm_impact_token": tok}
    assert client.put(f"{A}/roles/{rid}/permissions", headers=h, json=other).status_code == 409
    r = client.put(f"{A}/roles/{rid}/permissions", headers=h,
                   json={**want, "confirm_impact_token": tok})
    assert r.status_code == 200 and r.json()["permisos"] == want["codigos"]

    # Quitar un permiso: la asociación queda INACTIVA (historia), no se borra.
    tok = client.post(f"{A}/roles/{rid}/permissions/impact", headers=h,
                      json={"codigos": ["ADM.ROL.CONSULTA"]}).json()["confirm_impact_token"]
    client.put(f"{A}/roles/{rid}/permissions", headers=h,
               json={"codigos": ["ADM.ROL.CONSULTA"], "confirm_impact_token": tok})
    rows = owner.execute("SELECT p.codigo, rp.estado FROM app.rol_permiso rp JOIN app.permiso p "
                         "ON p.id = rp.permiso_id WHERE rp.rol_id = %s ORDER BY 1",
                         (rid,)).fetchall()
    assert rows == [("ADM.PERFIL.CONSULTA", "INACTIVO"), ("ADM.ROL.CONSULTA", "ACTIVO")]
    ev = events(owner, "IAM_ROLE_PERMISSIONS", rid)[-1]
    assert ev[0] == {"permisos": want["codigos"]} and ev[1] == {"permisos": ["ADM.ROL.CONSULTA"]}

    sys_role = owner.execute("SELECT id FROM app.rol WHERE codigo = 'ADMINISTRADOR_TOTAL'"
                             ).fetchone()[0]
    assert client.post(f"{A}/roles/{sys_role}/permissions/impact", headers=h,
                       json=want).status_code == 409
    assert client.post(f"{A}/roles/{rid}/permissions/impact", headers=h,
                       json={"codigos": ["ADM.NO.EXISTE"]}).status_code == 422


def test_role_status_with_impact(client, owner, admin):
    _, h = admin
    rid = client.post(f"{A}/roles", headers=h, json={
        "codigo": f"ZS_{uuid.uuid4().hex[:6].upper()}", "nombre": "S"}).json()["id"]
    body = {"estado": "INACTIVO"}
    assert client.post(f"{A}/roles/{rid}/status", headers=h, json=body).status_code == 422
    tok = client.post(f"{A}/roles/{rid}/status/impact", headers=h,
                      json=body).json()["confirm_impact_token"]
    r = client.post(f"{A}/roles/{rid}/status", headers=h,
                    json={**body, "confirm_impact_token": tok})
    assert r.status_code == 200 and r.json()["estado"] == "INACTIVO"


def test_permissions_create_and_status(client, owner, admin):
    _, h = admin
    code = f"IND.ZZ{uuid.uuid4().hex[:4].upper()}.CONSULTA"
    r = client.post(f"{A}/permissions", headers=h, json={"codigo": code, "nombre": "Z"})
    assert r.status_code == 201 and r.json()["categoria"] == "CONSULTA"
    pid = r.json()["id"]
    for bad in ("IND.X.LEER", "ZZ.X.CONSULTA"):
        assert client.post(f"{A}/permissions", headers=h,
                           json={"codigo": bad, "nombre": "x"}).status_code == 422
    rcode = f"ZPP_{uuid.uuid4().hex[:6].upper()}"
    ensure_role(owner, rcode, (code,))
    ensure_profile(owner, rcode, (rcode,))
    make_user(owner, perfil=rcode)
    imp = client.post(f"{A}/permissions/{pid}/status/impact", headers=h,
                      json={"estado": "INACTIVO"}).json()
    assert imp["perfiles_afectados"] == [rcode] and imp["usuarios_afectados"] == 1
    r = client.post(f"{A}/permissions/{pid}/status", headers=h,
                    json={"estado": "INACTIVO",
                          "confirm_impact_token": imp["confirm_impact_token"]})
    assert r.status_code == 200

    sys_perm = owner.execute("SELECT id FROM app.permiso WHERE codigo = 'ADM.ROL.CONSULTA'"
                             ).fetchone()[0]
    assert client.post(f"{A}/permissions/{sys_perm}/status/impact", headers=h,
                       json={"estado": "INACTIVO"}).status_code == 409
    r = client.patch(f"{A}/permissions/{sys_perm}", headers=h,
                     json={"descripcion": "Consultar roles"})
    assert r.status_code == 200  # R12: los permisos de sistema sí se describen


def test_modules_create_order_and_status(client, owner, admin):
    _, h = admin
    code = "Z" + "".join(chr(65 + int(c, 16) % 26) for c in uuid.uuid4().hex[:5])
    r = client.post(f"{A}/modules", headers=h,
                    json={"codigo": code, "nombre": "Z", "ruta_frontend": "/z"})
    assert r.status_code == 201
    mid = r.json()["id"]
    current = [m["codigo"] for m in client.get(f"{A}/modules", headers=h).json()]
    assert current[-1] == code
    assert client.put(f"{A}/modules/order", headers=h,
                      json={"codigos": current[:-1]}).status_code == 422
    new_order = [code] + current[:-1]
    assert client.put(f"{A}/modules/order", headers=h,
                      json={"codigos": new_order}).json() == new_order
    assert [m["codigo"] for m in client.get(f"{A}/modules", headers=h).json()] == new_order
    client.put(f"{A}/modules/order", headers=h, json={"codigos": current})  # restaurar

    adm = owner.execute("SELECT id FROM app.modulo WHERE codigo='ADM'").fetchone()[0]
    assert client.post(f"{A}/modules/{adm}/status", headers=h,
                       json={"estado": "INACTIVO"}).status_code == 409

    uid, red = make_user(owner, modulos=(code,))
    assert client.post(f"{A}/modules/{mid}/status", headers=h,
                       json={"estado": "INACTIVO"}).json()["asignaciones_a_revisar"] == []
    mods = client.get("/api/v1/me/modules", headers=bearer(token(client, red))).json()
    assert mods["modulos"] == []
    r = client.post(f"{A}/modules/{mid}/status", headers=h, json={"estado": "ACTIVO"}).json()
    assert [a["usuario_red"] for a in r["asignaciones_a_revisar"]] == [red]


def test_domains_and_parameters(client, owner, admin):
    _, h = admin
    r = client.post(f"{A}/domains", headers=h, json={
        "codigo": f"D_{uuid.uuid4().hex[:6].upper()}", "nombre": "Gobierno", "modulo": "ADM"})
    assert r.status_code == 201
    did = r.json()["id"]
    assert client.patch(f"{A}/domains/{did}", headers=h,
                        json={"descripcion": "x"}).status_code == 200
    assert client.post(f"{A}/domains/{did}/status", headers=h,
                       json={"estado": "INACTIVO"}).status_code == 200

    params = {p["clave"]: p for p in client.get(f"{A}/parameters", headers=h).json()}
    assert params["th.umbral_alerta_horas"]["valor"] in ("4", "6")
    for clave, valor, code in (("th.umbral_alerta_horas", "0", 422),
                               ("th.umbral_alerta_horas", "abc", 422),
                               ("th.hora_habitual", "25:00", 422),
                               ("th.hora_habitual", "07:30", 200),
                               ("no.existe", "1", 404)):
        assert client.patch(f"{A}/parameters/{clave}", headers=h,
                            json={"valor": valor}).status_code == code, (clave, valor)
    assert events(owner, "PAR_UPDATED", "th.hora_habitual")[-1][1] == {"valor": "07:30"}
    owner.execute("UPDATE ops.parametro SET valor = NULL WHERE clave = 'th.hora_habitual'")


def test_direct_operation_is_fail_closed(client, owner, admin):
    _, h = admin
    code = f"ZF_{uuid.uuid4().hex[:6].upper()}"
    owner.execute(f'REVOKE INSERT ON audit.evento FROM "{S.app_db_user}"')
    try:
        r = client.post(f"{A}/profiles", headers=h, json={"codigo": code, "nombre": "F"})
    finally:
        owner.execute(f'GRANT INSERT ON audit.evento TO "{S.app_db_user}"')
    assert r.status_code == 503
    assert owner.execute("SELECT count(*) FROM app.perfil WHERE codigo = %s",
                         (code,)).fetchone()[0] == 0


# =========================================================================== con aprobación

def alta_body(org, **over) -> dict:
    body = {"usuario_red": rand_red().upper(), "identificacion": uuid.uuid4().hex[:12],
            "nombre": "Ana", "primer_apellido": "Pérez", "correo": "ana@example.org",
            "perfil": "PRUEBA_FUNCIONAL", "gerencia_id": org["gerencia_id"],
            "area_id": org["area_id"], "cargo_id": org["cargo_id"], "tipo_alta": "NORMAL",
            "modulos": ["IND"]}
    return {**body, **over}


def test_user_creation_request(client, owner, admin, org):
    _, h = admin
    ensure_profile(owner, "PRUEBA_FUNCIONAL")
    body = alta_body(org)
    r = client.post(f"{A}/users", headers=h, json=body)
    assert r.status_code == 202, r.text
    out = r.json()
    assert out["tipo"] == "ALTA_USUARIO" and out["estado"] == "PENDIENTE"
    uid = out["usuario_id"]

    estado = owner.execute("SELECT estado FROM app.usuario WHERE id = %s", (uid,)).fetchone()[0]
    assert estado == "PENDIENTE_ALTA"
    assert owner.execute("SELECT count(*) FROM app.credencial WHERE usuario_id = %s",
                         (uid,)).fetchone()[0] == 0
    assert owner.execute("SELECT count(*) FROM app.usuario_modulo WHERE usuario_id = %s",
                         (uid,)).fetchone()[0] == 0  # módulos se asignan al aprobar (Fase 6)
    assert login(client, body["usuario_red"]).status_code == 401

    det = client.get(f"{A}/requests/{out['solicitud_id']}", headers=h).json()
    attrs = {i["atributo"]: i for i in det["items"]}
    assert attrs["usuario_red"]["valor_nuevo"] == body["usuario_red"].lower()
    assert attrs["modulos"]["valor_nuevo"] == ["IND"] and attrs["estado"]["valor_anterior"] is None
    assert det["usuario_objetivo"] == body["usuario_red"].lower()
    assert any(s["id"] == out["solicitud_id"] for s in client.get(
        f"{A}/requests", headers=h, params={"estado": "PENDIENTE"}).json()["items"])
    assert events(owner, "APR_REQUEST_CREATED", out["solicitud_id"])

    # Validaciones
    dup = client.post(f"{A}/users", headers=h,
                      json=alta_body(org, usuario_red=body["usuario_red"]))
    assert dup.status_code == 409 and dup.json()["error"]["details"]["usuario_red"] is True
    bad_area = alta_body(org, gerencia_id=org["otra_gerencia"])
    assert client.post(f"{A}/users", headers=h, json=bad_area).status_code == 422
    assert client.post(f"{A}/users", headers=h,
                       json={**alta_body(org), "empresa": "X"}).status_code == 422
    assert client.post(f"{A}/users", headers=h,
                       json=alta_body(org, usuario_red="aa11bb22")).status_code == 422
    assert client.post(f"{A}/users", headers=h,
                       json=alta_body(org, modulos=["NOEXISTE"])).status_code == 422
    owner.execute("UPDATE app.cargo SET estado='INACTIVO' WHERE id=%s", (org["cargo_id"],))
    assert client.post(f"{A}/users", headers=h, json=alta_body(org)).status_code == 422
    no_org = {k: v for k, v in alta_body(org).items() if k != "cargo_id"}
    assert client.post(f"{A}/users", headers=h, json=no_org).status_code == 422


def test_grouped_update_request_and_one_pending(client, owner, admin, org):
    _, h = admin
    uid, _ = make_user(owner)
    r = client.patch(f"{A}/users/{uid}", headers=h, json={
        "correo": "nuevo@example.org", "nombre": "Test", "primer_apellido": "Nuevo",
        **{k: org[k] for k in ("gerencia_id", "area_id", "cargo_id")}})
    assert r.status_code == 202, r.text
    det = client.get(f"{A}/requests/{r.json()['solicitud_id']}", headers=h).json()
    attrs = {i["atributo"]: (i["valor_anterior"], i["valor_nuevo"]) for i in det["items"]}
    # Solo los atributos que cambian (nombre ya era "Test"), con snapshot del valor anterior.
    assert set(attrs) == {"correo", "primer_apellido", "gerencia_id", "area_id", "cargo_id"}
    assert attrs["correo"] == ("t@x.co", "nuevo@example.org")
    assert owner.execute("SELECT correo FROM app.usuario WHERE id = %s",
                         (uid,)).fetchone()[0] == "t@x.co"  # nada aplicado aún

    again = client.post(f"{A}/users/{uid}/deactivate", headers=h,
                        json={"motivo": "Retiro voluntario confirmado"})
    assert again.status_code == 409 and "solicitud_pendiente" in again.json()["error"]["details"]

    other, _ = make_user(owner)
    assert client.patch(f"{A}/users/{other}", headers=h,
                        json={"nombre": "Test"}).status_code == 422  # sin cambios
    assert client.patch(f"{A}/users/{other}", headers=h,
                        json={"usuario_red": "b2b2b2b2"}).status_code == 422  # no editable


def test_modules_deactivation_reactivation_requests(client, owner, admin):
    admin_id, h = admin
    uid, _ = make_user(owner, modulos=("IND",))
    r = client.put(f"{A}/users/{uid}/modules", headers=h, json={"modulos": ["ADM", "IND"]})
    assert r.status_code == 202
    det = client.get(f"{A}/requests/{r.json()['solicitud_id']}", headers=h).json()
    assert det["items"][0]["valor_anterior"] == ["IND"]
    assert det["items"][0]["valor_nuevo"] == ["ADM", "IND"]

    u2, _ = make_user(owner)
    assert client.post(f"{A}/users/{u2}/deactivate", headers=h,
                       json={"motivo": "corto"}).status_code == 422
    assert client.post(f"{A}/users/{u2}/deactivate", headers=h,
                       json={"motivo": "Retiro de la organización"}).status_code == 202
    assert client.post(f"{A}/users/{u2}/reactivate", headers=h,
                       json={"motivo": "Reingreso del funcionario"}).status_code == 422

    u3, _ = make_user(owner, estado="INACTIVO")
    assert client.post(f"{A}/users/{u3}/reactivate", headers=h,
                       json={"motivo": "Reingreso del funcionario"}).status_code == 202

    # No dejar el sistema sin administradores (único admin activo).
    r = client.post(f"{A}/users/{admin_id}/deactivate", headers=h,
                    json={"motivo": "Prueba de último administrador"})
    assert r.status_code == 409
    r = client.put(f"{A}/users/{admin_id}/modules", headers=h, json={"modulos": ["IND"]})
    assert r.status_code == 409


def test_requests_are_immutable_in_db(client, owner, admin, runtime):
    _, h = admin
    uid, _ = make_user(owner)
    sid = client.post(f"{A}/users/{uid}/deactivate", headers=h,
                      json={"motivo": "Prueba de inmutabilidad"}).json()["solicitud_id"]
    with pytest.raises(psycopg.errors.CheckViolation, match="no se modifica"):
        owner.execute("UPDATE app.solicitud SET motivo = 'alterado' WHERE id = %s", (sid,))
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute("UPDATE app.solicitud_item SET valor_nuevo = '\"ACTIVO\"' "
                      "WHERE solicitud_id = %s", (sid,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute("DELETE FROM app.solicitud WHERE id = %s", (sid,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        owner.execute("INSERT INTO app.solicitud (id, tipo, origen, entidad, entidad_id, "
                      "solicitante_id) SELECT gen_random_uuid(), 'REACTIVACION_USUARIO', "
                      "'MANUAL', 'usuario', %s, solicitante_id FROM app.solicitud WHERE id = %s",
                      (uid, sid))
