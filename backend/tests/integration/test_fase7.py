"""Integración Fase 7: auditoría consultable/exportable, errores, notificaciones y worker."""

import asyncio
import io
import json

import httpx
import pytest
import redis
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.core.config import get_settings
from app.core.db import Database
from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool
from app.kernel.error_registry import record_error
from app.main import create_app
from app.modules.auth.application.maintenance import close_abandoned_sessions
from app.modules.auth.infrastructure.session_store import SessionStore
from app.modules.notifications.application.delivery import (
    MAX_ATTEMPTS,
    SmtpSender,
    process_batch,
)
from tests.integration.helpers import bearer, make_admin, make_user, token

pytestmark = pytest.mark.integration
S = get_settings()
A = "/api/v1/admin"
MAILPIT = f"http://{S.smtp_host}:8025/api/v1"


@pytest.fixture
def client():
    with TestClient(create_app(), base_url="https://testserver",
                    raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def admins(client, owner):
    """Dos administradores activos (destinatarios obligatorios)."""
    a1, red1 = make_admin(owner)
    owner.execute("UPDATE app.usuario SET correo = 'admin1@example.org' WHERE id = %s", (a1,))
    a2, red2 = make_user(owner, perfil="ADMINISTRADOR", modulos=("ADM",))
    owner.execute("UPDATE app.usuario SET correo = 'admin2@example.org' WHERE id = %s", (a2,))
    return (a1, bearer(token(client, red1))), (a2, bearer(token(client, red2)))


@pytest.fixture(autouse=True)
def clean_outbox(owner):
    """Aísla cada prueba: entregas previas fuera de la cola y Mailpit vacío."""
    owner.execute("UPDATE ops.entrega_notificacion SET estado = 'ENVIADA', enviada_en = now() "
                  "WHERE estado = 'PENDIENTE'")
    httpx.delete(f"{MAILPIT}/messages", timeout=5)
    yield


def run(coro):
    return asyncio.run(coro)


async def _with_db(fn):
    db = Database(S.sqlalchemy_url, pool_size=2, max_overflow=0)
    try:
        return await fn(db)
    finally:
        await db.dispose()


def deliver(sender=None):
    return run(_with_db(lambda db: process_batch(db.sessionmaker, sender or SmtpSender(S))))


def deliveries_for(owner, plantilla, origen):
    return owner.execute(
        "SELECT e.canal, u.usuario_red, e.estado, e.intentos FROM ops.entrega_notificacion e "
        "JOIN ops.notificacion n ON n.id = e.notificacion_id JOIN app.usuario u "
        "ON u.id = e.usuario_id WHERE n.plantilla = %s AND n.origen_id = %s ORDER BY 1, 2",
        (plantilla, origen)).fetchall()


# --------------------------------------------------------------------------- §4 generación

def test_requests_notify_both_admins_on_every_channel(client, owner, admins):
    (_, h1), _ = admins
    uid, red = make_user(owner)
    rid = client.post(f"{A}/users/{uid}/deactivate", headers=h1,
                      json={"motivo": "Retiro confirmado por TH"}).json()["solicitud_id"]
    created = deliveries_for(owner, "APR_REQUEST_CREATED", rid)
    assert len(created) == 4 and {c[0] for c in created} == {"BANDEJA", "CORREO"}
    assert {c[2] for c in created} == {"PENDIENTE"}
    body = owner.execute("SELECT cuerpo FROM ops.notificacion WHERE plantilla = "
                         "'APR_REQUEST_CREATED' AND origen_id = %s", (rid,)).fetchone()[0]
    assert red in body and "INHABILITACION_USUARIO" in body

    client.post(f"{A}/requests/{rid}/approve", headers=h1)
    assert len(deliveries_for(owner, "APR_APPROVED", rid)) == 4


# --------------------------------------------------------------------------- §6-7 entrega y bandeja

def test_worker_delivers_inbox_and_email(client, owner, admins):
    (a1, h1), (_, h2) = admins
    uid, _ = make_user(owner)
    rid = client.patch(f"{A}/users/{uid}", headers=h1,
                       json={"correo": "nuevo@example.org"}).json()["solicitud_id"]
    r = deliver()
    assert r.enviadas >= 4 and r.reintentos == 0
    assert {d[2] for d in deliveries_for(owner, "APR_REQUEST_CREATED", rid)} == {"ENVIADA"}

    msgs = httpx.get(f"{MAILPIT}/messages", timeout=5).json()["messages"]
    to = {m["To"][0]["Address"] for m in msgs}
    assert {"admin1@example.org", "admin2@example.org"} <= to
    assert all("#" in m["Subject"] for m in msgs)

    inbox = client.get("/api/v1/notifications", headers=h1).json()
    item = next(i for i in inbox["items"] if i["evento"] == "APR_REQUEST_CREATED")
    assert item["leida"] is False and inbox["no_leidas"] >= 1
    assert client.post(f"/api/v1/notifications/{item['id']}/read", headers=h1).status_code == 204
    after = client.get("/api/v1/notifications", headers=h1,
                       params={"solo_no_leidas": True}).json()["items"]
    assert item["id"] not in [i["id"] for i in after]
    # Una entrega ajena no se puede leer ni marcar (404, no revela existencia).
    assert client.post(f"/api/v1/notifications/{item['id']}/read", headers=h2).status_code == 404
    _, fred = make_user(owner)
    assert client.get("/api/v1/notifications",
                      headers=bearer(token(client, fred))).json()["items"] == []
    adm = client.get(f"{A}/notifications/deliveries", headers=h1,
                     params={"estado": "ENVIADA", "canal": "CORREO"}).json()
    assert any(d["evento"] == "APR_REQUEST_CREATED" for d in adm)


class FailingSender:
    async def send(self, to, subject, body):
        raise ConnectionRefusedError("smtp caído")


def test_smtp_down_inbox_still_delivered_then_exhausted(client, owner, admins):
    (_, h1), _ = admins
    uid, _ = make_user(owner)
    rid = client.post(f"{A}/users/{uid}/deactivate", headers=h1,
                      json={"motivo": "Prueba de SMTP caído"}).json()["solicitud_id"]
    deliver(FailingSender())
    rows = deliveries_for(owner, "APR_REQUEST_CREATED", rid)
    assert {(c, e) for c, _, e, _ in rows} == {("BANDEJA", "ENVIADA"), ("CORREO", "PENDIENTE")}
    wait = owner.execute(
        "SELECT min(extract(epoch FROM proximo_intento_en - now())) FROM ops.entrega_notificacion "
        "e JOIN ops.notificacion n ON n.id = e.notificacion_id WHERE n.origen_id = %s "
        "AND e.canal = 'CORREO'", (rid,)).fetchone()[0]
    assert 50 < float(wait) <= 60  # 1.er reintento a 1 min

    for _ in range(MAX_ATTEMPTS):
        owner.execute("UPDATE ops.entrega_notificacion SET proximo_intento_en = now() - "
                      "interval '1 second' WHERE estado = 'PENDIENTE'")
        deliver(FailingSender())
    rows = deliveries_for(owner, "APR_REQUEST_CREATED", rid)
    assert [(c, e, n) for c, _, e, n in rows if c == "CORREO"] == [
        ("CORREO", "AGOTADA", MAX_ATTEMPTS)] * 2
    alerts = owner.execute(
        "SELECT DISTINCT e.canal FROM ops.entrega_notificacion e JOIN ops.notificacion n "
        "ON n.id = e.notificacion_id WHERE n.plantilla = 'NOT_DELIVERY_EXHAUSTED'").fetchall()
    assert alerts == [("BANDEJA",)]  # alerta técnica solo por bandeja (sin bucle de correo)
    assert owner.execute("SELECT count(*) FROM ops.registro_error WHERE tipo = "
                         "'DELIVERY_EXHAUSTED'").fetchone()[0] >= 2
    # La operación de origen no se vio afectada.
    assert owner.execute("SELECT estado FROM app.solicitud WHERE id = %s",
                         (rid,)).fetchone()[0] == "PENDIENTE"


# --------------------------------------------------------------------------- §5 D-NOT-001

def test_notification_generation_failure_does_not_revert_operation(client, owner, admins):
    (_, h1), _ = admins
    uid, _ = make_user(owner)
    rid = client.patch(f"{A}/users/{uid}", headers=h1,
                       json={"correo": "dnot@example.org"}).json()["solicitud_id"]
    owner.execute(f'REVOKE INSERT ON ops.notificacion FROM "{S.app_db_user}"')
    try:
        r = client.post(f"{A}/requests/{rid}/approve", headers=h1)
    finally:
        owner.execute(f'GRANT INSERT ON ops.notificacion TO "{S.app_db_user}"')
    assert r.status_code == 200
    assert owner.execute("SELECT correo FROM app.usuario WHERE id = %s",
                         (uid,)).fetchone()[0] == "dnot@example.org"
    assert deliveries_for(owner, "APR_APPROVED", rid) == []
    assert owner.execute("SELECT count(*) FROM ops.registro_error WHERE tipo = "
                         "'GENERATION_FAILED' AND diagnostico->>'origen_id' = %s",
                         (rid,)).fetchone()[0] == 1


# --------------------------------------------------------------------------- §1 auditoría

def test_audit_query_export_and_verify_are_audited(client, owner, admins, runtime):
    (a1, h1), _ = admins
    runtime.execute("INSERT INTO audit.evento (id, actor_tipo, categoria, accion, resultado, "
                    "motivo, correlation_id) VALUES (gen_random_uuid(), 'SISTEMA', 'PRUEBA', "
                    "'ZZ_FORMULA', 'EXITO', '=HYPERLINK(\"http://x\")', 'corr-formula-0001')")
    r = client.get(f"{A}/audit/events", headers=h1,
                   params={"correlation_id": "corr-formula-0001"})
    assert r.status_code == 200 and r.json()["total"] == 1
    assert r.json()["items"][0]["accion"] == "ZZ_FORMULA"

    x = client.post(f"{A}/audit/events/export", headers=h1,
                    json={"correlation_id": "corr-formula-0001"})
    assert x.status_code == 200 and x.headers["x-export-truncated"] == "false"
    assert x.headers["content-type"].startswith("application/vnd.openxmlformats")
    rows = list(load_workbook(io.BytesIO(x.content)).active.iter_rows(values_only=True))
    header, data = rows[0], rows[1]
    assert data[header.index("motivo")].startswith("'=")  # fórmula neutralizada
    assert client.post(f"{A}/audit/events/export", headers=h1,
                       json={"empresa": "X"}).status_code == 422

    v = client.get(f"{A}/audit/verify", headers=h1).json()
    assert v["integra"] is True and v["total_eventos"] > 0

    acts = [x[0] for x in owner.execute(
        "SELECT accion FROM audit.evento WHERE actor_id = %s AND categoria = 'AUDITORIA' "
        "ORDER BY seq", (a1,)).fetchall()]
    assert acts == ["AUD_QUERIED", "AUD_EXPORTED", "AUD_VERIFIED"]
    for m in ("PUT", "PATCH", "DELETE"):
        assert client.request(m, f"{A}/audit/events", headers=h1).status_code == 405


def test_users_export_without_empresa_and_audited(client, owner, admins):
    (a1, h1), _ = admins
    make_user(owner, estado="INACTIVO")
    x = client.post(f"{A}/users/export", headers=h1, json={"estado": "INACTIVO"})
    assert x.status_code == 200
    rows = list(load_workbook(io.BytesIO(x.content)).active.iter_rows(values_only=True))
    assert "empresa" not in " ".join(str(c).lower() for c in rows[0])
    assert len(rows) > 1 and all(r[rows[0].index("estado")] == "INACTIVO" for r in rows[1:])
    det = owner.execute("SELECT detalle FROM audit.evento WHERE accion = 'USR_EXPORTED' "
                        "AND actor_id = %s ORDER BY seq DESC LIMIT 1", (a1,)).fetchone()[0]
    assert det["filas"] == len(rows) - 1 and det["filtros"] == {"estado": "INACTIVO"}
    _, fred = make_user(owner)
    assert client.post(f"{A}/users/export", headers=bearer(token(client, fred)),
                       json={}).status_code == 403


# --------------------------------------------------------------------------- §3 errores

def test_error_registry_attention(client, owner, admins):
    (a1, h1), _ = admins
    eid = run(_with_db(lambda db: record_error(
        db.sessionmaker, categoria="INTEGRACION", componente="prueba", tipo="ZZ_ERROR",
        descripcion="error de prueba", severidad="MEDIA")))
    items = client.get(f"{A}/errors", headers=h1, params={"categoria": "INTEGRACION"}).json()
    assert any(i["id"] == str(eid) for i in items["items"])
    r = client.patch(f"{A}/errors/{eid}", headers=h1, json={"estado_atencion": "EN_ATENCION"})
    assert r.status_code == 200 and r.json()["estado_atencion"] == "EN_ATENCION"
    assert client.patch(f"{A}/errors/{eid}", headers=h1,
                        json={"estado_atencion": "EN_ATENCION"}).status_code == 422
    ev = owner.execute("SELECT valor_anterior, valor_nuevo FROM audit.evento WHERE accion = "
                       "'ERR_STATUS_CHANGED' AND entidad_id = %s", (str(eid),)).fetchone()
    assert ev == ({"estado_atencion": "ABIERTO"}, {"estado_atencion": "EN_ATENCION"})
    assert client.delete(f"{A}/errors/{eid}", headers=h1).status_code == 405


# --------------------------------------------------------------------------- §8 spool

def test_spool_flush_records_and_notifies(owner, admins, tmp_path):
    spool = IncidentSpool(tmp_path)
    spool.record(AuditEntry(categoria="USUARIOS", accion="USR_CREATED", modulo="ADM"),
                 AuditContext.system(), "OperationalError")
    n = run(_with_db(lambda db: spool.flush(db.sessionmaker)))
    assert n == 1
    assert owner.execute("SELECT count(*) FROM ops.notificacion WHERE plantilla = "
                         "'OPS_AUDIT_OUTAGE' AND cuerpo LIKE '%1 operación%'").fetchone()[0] >= 1


# ---------------------------------------------------------------- §9 sesiones abandonadas

def test_worker_closes_abandoned_sessions(client, owner):
    uid, red = make_user(owner)
    token(client, red)
    sid = owner.execute("SELECT id FROM app.sesion WHERE usuario_id = %s AND finalizada_en "
                        "IS NULL", (uid,)).fetchone()[0]
    r = redis.Redis(host=S.redis_host, port=S.redis_port,
                    password=S.redis_password.get_secret_value())
    r.delete(f"so:sess:{sid}")
    r.close()
    owner.execute("UPDATE app.sesion SET ultima_actividad = now() - interval '1 hour' "
                  "WHERE id = %s", (sid,))

    async def go(db):
        import redis.asyncio as aioredis

        c = aioredis.Redis(host=S.redis_host, port=S.redis_port,
                           password=S.redis_password.get_secret_value())
        try:
            return await close_abandoned_sessions(db.sessionmaker, SessionStore(c, 900),
                                                  IncidentSpool(S.spool_dir), 900)
        finally:
            await c.aclose()

    assert run(_with_db(go)) >= 1
    assert owner.execute("SELECT motivo_fin FROM app.sesion WHERE id = %s",
                         (sid,)).fetchone()[0] == "INACTIVIDAD"
    det = owner.execute("SELECT detalle FROM audit.evento WHERE accion = 'AUTH_SESSION_EXPIRED' "
                        "AND entidad_id = %s", (str(sid),)).fetchone()[0]
    assert json.loads(json.dumps(det))["origen"] == "worker"
