"""Integración Fase 8: integración con Talento Humano (DD-03/04/05, REQ-TH-*)."""

import asyncio
import io
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.core.config import get_settings
from app.core.db import Database
from app.kernel.audit import IncidentSpool
from app.main import create_app
from app.modules.th.application.intake import check_missing_daily_file
from app.modules.th.application.processor import process_next
from tests.integration.helpers import bearer, make_admin, make_user, rand_red, token

pytestmark = pytest.mark.integration
S = get_settings()
A = "/api/v1/admin"
HDR = ["IDENTIFICACION", "NOMBRES", "PRIMER_APELLIDO", "CORREO", "USUARIO_RED",
       "CODIGO_GERENCIA", "GERENCIA", "CODIGO_AREA", "AREA", "CODIGO_CARGO", "CARGO", "EMPRESA"]


def xlsx(headers, rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def person(ident, g="GA", a="AA", c=101, red=None):
    return [ident, "Nombre", "Apellido", f"{ident.lower()}@example.org", red,
            g, f"Gerencia {g}", a, f"Área {a}", c, f"Cargo {c}", "ACME S.A."]


@pytest.fixture
def client():
    with TestClient(create_app(), base_url="https://testserver",
                    raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def admin(client, owner):
    uid, red = make_admin(owner)
    return uid, bearer(token(client, red))


def upload(client, h, tipo, content, name="planta.xlsx", **form):
    return client.post(f"{A}/th/files", headers=h, data={"tipo": tipo, **form},
                       files={"archivo": (name, content, "application/octet-stream")})


async def _process_all() -> int:
    db = Database(S.sqlalchemy_url, pool_size=2, max_overflow=0)
    n = 0
    try:
        while await process_next(db.sessionmaker, IncidentSpool(S.spool_dir)):
            n += 1
    finally:
        await db.dispose()
    return n


def process_all() -> int:
    return asyncio.run(_process_all())


def execution(owner, eid) -> dict:
    row = owner.execute("SELECT estado, estadisticas, ruta_temporal, archivo_eliminado_en, "
                        "error, intentos FROM app.ejecucion_th WHERE id = %s", (eid,)).fetchone()
    return dict(zip(("estado", "stats", "ruta", "eliminado", "error", "intentos"), row,
                    strict=True))


def set_ident(owner, uid, ident):
    owner.execute("UPDATE app.usuario SET identificacion = %s WHERE id = %s", (ident, uid))


# --------------------------------------------------------------------------- recepción

def test_upload_validation_and_file_lifecycle(client, owner, admin):
    _, h = admin
    assert upload(client, h, "ACTIVA", b"hola", name="x.txt").status_code == 422
    assert upload(client, h, "ACTIVA", b"no es zip").status_code == 422
    r = upload(client, h, "ACTIVA", xlsx(["IDENTIFICACION"], [["X1"]]))  # estructura inválida
    assert r.status_code == 202
    eid = r.json()["ejecucion_id"]
    path = execution(owner, eid)["ruta"]
    assert Path(path).exists() and oct(Path(path).stat().st_mode)[-3:] == "600"
    process_all()
    ex = execution(owner, eid)
    assert ex["estado"] == "RECHAZADA" and "faltan columnas" in ex["error"]
    assert ex["ruta"] is None and ex["eliminado"] and not Path(path).exists()  # REQ-TH-08
    assert owner.execute("SELECT count(*) FROM ops.notificacion WHERE plantilla = "
                         "'TH_EXECUTION_REJECTED' AND origen_id = %s", (eid,)).fetchone()[0] == 1


# --------------------------------------------------------------------------- planta activa

def test_active_plant_full_reconciliation(client, owner, admin):
    _, h = admin
    sfx = uuid.uuid4().hex[:5].upper()
    a_id, a_red = make_user(owner)
    b_id, _ = make_user(owner)
    set_ident(owner, a_id, f"A-{sfx}")
    set_ident(owner, b_id, f"B-{sfx}")
    g, ar = f"G{sfx}", f"A{sfx}"
    rows = [person(f"A-{sfx}", g, ar, 7001), person(f"N-{sfx}", g, ar, 7002),
            person(f"E-{sfx}", g, ar, "abc"), person(f"D-{sfx}", g, ar),
            person(f"D-{sfx}", g, ar)]
    content = xlsx(HDR, rows)
    r = upload(client, h, "ACTIVA", content)
    eid = r.json()["ejecucion_id"]
    process_all()
    ex = execution(owner, eid)
    assert ex["estado"] == "PARCIAL"
    st = ex["stats"]
    assert (st["filas"], st["ok"], st["errores"]) == (5, 2, 3)
    assert st["catalogos"]["gerencia_activos"] == 1 and st["ausentes_nuevos"] >= 1

    # Empresa nunca se persiste (REQ-TH-12).
    dump = json.dumps(owner.execute(
        "SELECT r.detalle, v.contenido FROM app.resultado_fila_th r LEFT JOIN "
        "app.propuesta_th_version v ON v.ejecucion_id = r.ejecucion_id WHERE r.ejecucion_id = %s",
        (eid,)).fetchall(), default=str)
    assert "ACME" not in dump and "empresa" not in dump.lower()

    # Catálogos sincronizados por código; usuario A con cambio org → solicitud TH.
    assert owner.execute("SELECT count(*) FROM app.gerencia WHERE codigo = %s AND estado = "
                         "'ACTIVO'", (g,)).fetchone()[0] == 1
    sol = owner.execute("SELECT id, tipo, origen, solicitante_id, propuesta_version_id FROM "
                        "app.solicitud WHERE entidad_id = %s AND estado = 'PENDIENTE'",
                        (a_id,)).fetchone()
    assert sol[1:4] == ("MODIFICACION_USUARIO", "TH", None) and sol[4] is not None
    # Nuevo funcionario → propuesta (no se crea cuenta).
    prop = client.get(f"{A}/th/proposals", headers=h,
                      params={"tipo": "NUEVO_FUNCIONARIO"}).json()
    assert any(p["identificacion"] == f"N-{sfx}" for p in prop)
    assert owner.execute("SELECT count(*) FROM app.usuario WHERE identificacion = %s",
                         (f"N-{sfx}",)).fetchone()[0] == 0
    # B ausente → alerta, sin cambio de estado.
    alerts = client.get(f"{A}/th/alerts", headers=h).json()
    assert any(a["tipo"] == "USUARIO_AUSENTE" for a in alerts)
    assert owner.execute("SELECT estado FROM app.usuario WHERE id = %s",
                         (b_id,)).fetchone()[0] == "ACTIVO"
    rws = client.get(f"{A}/th/executions/{eid}/rows", headers=h,
                     params={"resultado": "ERROR"}).json()
    assert {tuple(sorted(x["detalle"]["errores"])) for x in rws} == {
        ("CODIGO_CARGO_FORMATO",), ("IDENTIFICACION_DUPLICADA",)}

    # Duplicado (mismo SHA-256) → 409 + notificación; reproceso con motivo → ejecución vinculada.
    again = upload(client, h, "ACTIVA", content)
    assert again.status_code == 409 and again.json()["error"]["code"] == "TH_DUPLICATE"
    assert owner.execute("SELECT count(*) FROM ops.notificacion WHERE plantilla = 'TH_DUPLICATE' "
                         "AND origen_id = (SELECT encode(archivo_sha256, 'hex') FROM "
                         "app.ejecucion_th WHERE id = %s)", (eid,)).fetchone()[0] == 1
    assert upload(client, h, "ACTIVA", content, reproceso_de=eid,
                  motivo="corto").status_code == 422
    rep = upload(client, h, "ACTIVA", content, reproceso_de=eid,
                 motivo="Corrección de plantilla en TH")
    assert rep.status_code == 202
    detail = client.get(f"{A}/th/executions/{rep.json()['ejecucion_id']}", headers=h).json()
    assert detail["reproceso_de"] is not None and detail["motivo_reproceso"]
    process_all()

    # Nueva versión: A cambia otra vez → la solicitud anterior pasa a SUPERADA.
    rows2 = [person(f"A-{sfx}", g, ar, 7003), person(f"N-{sfx}", g, ar, 7002)]
    upload(client, h, "ACTIVA", xlsx(HDR, rows2))
    process_all()
    assert owner.execute("SELECT estado FROM app.solicitud WHERE id = %s",
                         (sol[0],)).fetchone()[0] == "SUPERADA"
    r = client.post(f"{A}/requests/{sol[0]}/approve", headers=h)
    assert r.status_code == 409
    new_sol = owner.execute("SELECT id FROM app.solicitud WHERE entidad_id = %s AND estado = "
                            "'PENDIENTE'", (a_id,)).fetchone()[0]
    assert client.post(f"{A}/requests/{new_sol}/approve", headers=h).status_code == 200
    cargo = owner.execute("SELECT c.codigo_cargo FROM app.usuario u JOIN app.cargo c "
                          "ON c.id = u.cargo_id WHERE u.id = %s", (a_id,)).fetchone()[0]
    assert cargo == 7003
    # El cargo 7001 ya no está en la planta → INACTIVO (no se borra).
    assert owner.execute("SELECT estado FROM app.cargo WHERE codigo_cargo = 7001"
                         ).fetchone()[0] == "INACTIVO"

    # B reaparece → su alerta se cierra; vuelve a faltar → alerta nueva.
    upload(client, h, "ACTIVA", xlsx(HDR, rows2 + [person(f"B-{sfx}", g, ar, 7002)]))
    process_all()
    assert owner.execute("SELECT count(*) FROM app.alerta_th WHERE usuario_id = %s AND "
                         "cerrada_en IS NULL", (b_id,)).fetchone()[0] == 0
    upload(client, h, "ACTIVA", xlsx(HDR, rows2 + [person(f"Z-{sfx}", g, ar, 7002)]))
    process_all()
    assert owner.execute("SELECT count(*) FROM app.alerta_th WHERE usuario_id = %s",
                         (b_id,)).fetchone()[0] == 2


def test_new_employee_decision_and_alta_types(client, owner, admin):
    _, h = admin
    sfx = uuid.uuid4().hex[:5].upper()
    red = rand_red()
    upload(client, h, "ACTIVA", xlsx(HDR, [person(f"N2-{sfx}", f"G{sfx}", f"A{sfx}", 7101,
                                                  red=red)]))
    process_all()
    prop = next(p for p in client.get(f"{A}/th/proposals", headers=h).json()
                if p["identificacion"] == f"N2-{sfx}")
    owner.execute("INSERT INTO app.perfil (codigo, nombre) VALUES ('PRUEBA_FUNCIONAL', 'P') "
                  "ON CONFLICT DO NOTHING")
    r = client.post(f"{A}/th/proposals/{prop['id']}/decide", headers=h,
                    json={"tipo_alta": "NORMAL", "perfil": "PRUEBA_FUNCIONAL",
                          "modulos": ["IND"]})
    assert r.status_code == 202, r.text
    assert client.get(f"{A}/th/proposals/{prop['id']}", headers=h).json()["estado"] == "CERRADA"
    ok = client.post(f"{A}/requests/{r.json()['solicitud_id']}/approve", headers=h)
    assert ok.status_code == 200
    assert owner.execute("SELECT usuario_red, estado FROM app.usuario WHERE id = %s",
                         (r.json()["usuario_id"],)).fetchone() == (red, "ACTIVO")

    # DD-02: NORMAL exige figurar en la última planta; EXCEPCIONAL exige motivo.
    org = owner.execute("SELECT g.id, a.id, c.id FROM app.area a JOIN app.gerencia g ON "
                        "g.id = a.gerencia_id, app.cargo c WHERE a.codigo = %s AND "
                        "c.codigo_cargo = 7101", (f"A{sfx}",)).fetchone()
    base = {"usuario_red": rand_red(), "identificacion": f"X-{sfx}", "nombre": "X",
            "primer_apellido": "Y", "correo": "x@example.org", "perfil": "PRUEBA_FUNCIONAL",
            "gerencia_id": str(org[0]), "area_id": str(org[1]), "cargo_id": str(org[2])}
    assert client.post(f"{A}/users", headers=h,
                       json={**base, "tipo_alta": "NORMAL"}).status_code == 422
    assert client.post(f"{A}/users", headers=h,
                       json={**base, "tipo_alta": "EXCEPCIONAL"}).status_code == 422
    assert client.post(f"{A}/users", headers=h, json={
        **base, "tipo_alta": "EXCEPCIONAL", "motivo": "Contratista autorizado"}).status_code == 202


# --------------------------------------------------------------------------- retirados

def test_retirements_unambiguous_match_and_priority(client, owner, admin):
    _, h = admin
    sfx = uuid.uuid4().hex[:5].upper()
    r1, red1 = make_user(owner)
    r2, _ = make_user(owner)
    set_ident(owner, r1, f"R1-{sfx}")
    set_ident(owner, r2, f"R2-{sfx}")
    hdr = ["IDENTIFICACION", "FECHA_RETIRO", "USUARIO_RED"]
    act = upload(client, h, "ACTIVA", xlsx(HDR, [person(f"R1-{sfx}", f"G{sfx}", f"A{sfx}")]))
    ret = upload(client, h, "RETIRADOS", xlsx(hdr, [
        [f"R1-{sfx}", "2026-11-01", red1], [f"R2-{sfx}", "2026-11-01", "z9z9z9z9"],
        [f"NO-{sfx}", "2026-11-01", None]]))
    process_all()
    fin = {e: owner.execute("SELECT finalizada_en FROM app.ejecucion_th WHERE id = %s",
                            (e,)).fetchone()[0]
           for e in (act.json()["ejecucion_id"], ret.json()["ejecucion_id"])}
    assert fin[ret.json()["ejecucion_id"]] < fin[act.json()["ejecucion_id"]]  # REQ-TH-02

    rows = {x["identificacion"]: x for x in client.get(
        f"{A}/th/executions/{ret.json()['ejecucion_id']}/rows", headers=h).json()}
    assert rows[f"R1-{sfx}"]["accion"] == "SOLICITUD_INHABILITACION"
    assert rows[f"R2-{sfx}"]["accion"] == "COINCIDENCIA_AMBIGUA"
    assert rows[f"NO-{sfx}"]["accion"] == "USUARIO_INEXISTENTE"
    sol = owner.execute("SELECT id, origen, motivo FROM app.solicitud WHERE entidad_id = %s "
                        "AND tipo = 'INHABILITACION_USUARIO'", (r1,)).fetchone()
    assert sol[1] == "TH" and "Retiro reportado" in sol[2]
    # Nunca inhabilitación automática: sigue ACTIVO hasta aprobar.
    assert owner.execute("SELECT estado FROM app.usuario WHERE id = %s",
                         (r1,)).fetchone()[0] == "ACTIVO"
    assert client.post(f"{A}/requests/{sol[0]}/approve", headers=h).status_code == 200
    assert owner.execute("SELECT estado FROM app.usuario WHERE id = %s",
                         (r1,)).fetchone()[0] == "INACTIVO"


# --------------------------------------------------------------------------- fallas técnicas

def test_technical_retries_then_failed(client, owner, admin):
    _, h = admin
    r = upload(client, h, "RETIRADOS", xlsx(["IDENTIFICACION", "FECHA_RETIRO"],
                                            [["T-1", "2026-11-01"]]))
    eid = r.json()["ejecucion_id"]
    real = execution(owner, eid)["ruta"]
    owner.execute("UPDATE app.ejecucion_th SET ruta_temporal = '/nonexistent/x.xlsx' "
                  "WHERE id = %s", (eid,))
    process_all()
    ex = execution(owner, eid)
    assert (ex["estado"], ex["intentos"]) == ("PENDIENTE", 1)
    wait = owner.execute("SELECT extract(epoch FROM proximo_intento_en - now()) FROM "
                         "app.ejecucion_th WHERE id = %s", (eid,)).fetchone()[0]
    assert 50 < float(wait) <= 60
    for _ in range(2):
        owner.execute("UPDATE app.ejecucion_th SET proximo_intento_en = now() WHERE id = %s",
                      (eid,))
        process_all()
    ex = execution(owner, eid)
    assert (ex["estado"], ex["intentos"]) == ("FALLIDA", 3) and ex["ruta"] is None
    assert owner.execute("SELECT count(*) FROM ops.notificacion WHERE plantilla = "
                         "'TH_EXECUTION_FAILED' AND origen_id = %s", (eid,)).fetchone()[0] == 1
    assert owner.execute("SELECT count(*) FROM ops.registro_error WHERE tipo = "
                         "'TH_RETRY_EXHAUSTED' AND diagnostico->>'ejecucion_id' = %s",
                         (eid,)).fetchone()[0] == 1
    Path(real).unlink(missing_ok=True)


# --------------------------------------------------------------------------- archivo no recibido

def test_missing_daily_file_alert_once_per_period(client, owner, admin):
    _, h = admin
    owner.execute("UPDATE ops.parametro SET valor = '06:00' WHERE clave = 'th.hora_habitual'")
    owner.execute("UPDATE app.alerta_th SET cerrada_en = now() WHERE tipo = "
                  "'ARCHIVO_NO_RECIBIDO' AND cerrada_en IS NULL")
    tz = ZoneInfo("America/Bogota")
    future = (datetime.now(tz) + timedelta(days=3)).replace(hour=11, minute=0)

    async def check(when):
        db = Database(S.sqlalchemy_url, pool_size=1, max_overflow=0)
        try:
            return await check_missing_daily_file(db.sessionmaker, IncidentSpool(S.spool_dir),
                                                  now=when)
        finally:
            await db.dispose()

    try:
        assert asyncio.run(check(future.replace(hour=9))) is False  # antes de 06:00 + 4 h
        assert asyncio.run(check(future)) is True
        assert asyncio.run(check(future + timedelta(days=1))) is False  # mismo periodo
        upload(client, h, "ACTIVA", xlsx(HDR, [person(f"M-{uuid.uuid4().hex[:5]}")]))
        process_all()  # llega una planta activa → se cierra la alerta
        assert owner.execute("SELECT count(*) FROM app.alerta_th WHERE tipo = "
                             "'ARCHIVO_NO_RECIBIDO' AND cerrada_en IS NULL").fetchone()[0] == 0
        assert owner.execute("SELECT count(*) FROM ops.notificacion WHERE plantilla = "
                             "'TH_FILE_MISSING'").fetchone()[0] >= 1
    finally:
        owner.execute("UPDATE ops.parametro SET valor = NULL WHERE clave = 'th.hora_habitual'")
