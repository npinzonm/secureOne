"""Integración Fase 2: privilegios, inmutabilidad, cadena de hash, fail-closed y errores.

Criterios de aceptación FASE-2 §2–§7.
"""

import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import AuditUnavailableError
from app.core.logging import correlation_id_var
from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool
from app.kernel.error_registry import record_error
from app.kernel.unit_of_work import UnitOfWork
from app.main import create_app

pytestmark = pytest.mark.integration

ROLE = get_settings().app_db_user


def _insert_event(conn, accion: str, **extra) -> None:
    cols = {"id": str(uuid.uuid4()), "actor_tipo": "SISTEMA", "categoria": "PRUEBA",
            "accion": accion, "resultado": "EXITO", **extra}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    # Nombres de columna fijos del propio test (no provienen de entrada externa).
    query = f"INSERT INTO audit.evento ({names}) VALUES ({marks})"  # noqa: S608
    conn.execute(query, list(cols.values()))


def _verify(conn) -> tuple[int, int | None]:
    q = "SELECT total, primer_seq_invalido FROM audit.verificar_cadena()"
    return conn.execute(q).fetchone()


# --------------------------------------------------------------------------- privilegios (§2)

@pytest.mark.parametrize(
    "stmt",
    [
        "CREATE TABLE app.no_ddl (x int)",
        "DELETE FROM app.zz_prueba",
        "DELETE FROM ops.registro_error",
        "UPDATE audit.evento SET motivo = 'x'",
        "DELETE FROM audit.evento",
        "TRUNCATE audit.evento",
        "CREATE TABLE public.no_ddl (x int)",
    ],
)
def test_runtime_role_cannot(runtime, stmt):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runtime.execute(stmt)


def test_runtime_role_is_not_superuser_and_cannot_create_roles(runtime):
    row = runtime.execute(
        "SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert row == (False, False, False)


# --------------------------------------------------------------------------- inmutabilidad (§3)

@pytest.mark.parametrize(
    "stmt",
    ["UPDATE audit.evento SET motivo = 'x'", "DELETE FROM audit.evento", "TRUNCATE audit.evento"],
)
def test_even_owner_cannot_modify_audit(owner, runtime, stmt):
    _insert_event(runtime, "PRUEBA_INMUTABLE")
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="inmutable"):
        owner.execute(stmt)


# --------------------------------------------------------------------------- cadena (§4)

def test_chain_is_computed_by_db_and_verifies(runtime):
    _insert_event(runtime, "PRUEBA_CADENA_1")
    # Valores falsificados por el cliente: la BD los sobrescribe.
    _insert_event(runtime, "PRUEBA_CADENA_2", ocurrido_en="2000-01-01T00:00:00Z",
                  hash=b"falso", hash_previo=b"falso")
    rows = runtime.execute(
        "SELECT seq, ocurrido_en, hash_previo, hash FROM audit.evento ORDER BY seq DESC LIMIT 2"
    ).fetchall()
    last, prev = rows[0], rows[1]
    assert last[1].year >= 2026
    assert last[2] == prev[3]          # enlazado al anterior
    assert last[3] != b"falso" and len(last[3]) == 32
    total, invalid = _verify(runtime)
    assert total >= 2 and invalid is None


def test_tampering_is_detected(owner, runtime):
    _insert_event(runtime, "PRUEBA_MANIPULACION")
    target = runtime.execute("SELECT max(seq) FROM audit.evento").fetchone()[0]
    # Manipulación simulada DENTRO de una transacción que se revierte (DDL transaccional en PG).
    with owner.transaction(force_rollback=True):
        owner.execute("ALTER TABLE audit.evento DISABLE TRIGGER evento_inmutable")
        owner.execute("UPDATE audit.evento SET motivo = 'alterado' WHERE seq = %s", (target,))
        _, invalid = _verify(owner)
        assert invalid == target
    assert _verify(runtime)[1] is None  # tras el rollback la cadena vuelve a ser íntegra


# --------------------------------------------------------------------------- fail-closed (§5)

async def test_fail_closed_blocks_business_change_and_recovers(owner, db, tmp_path):
    spool = IncidentSpool(tmp_path)
    item_id = uuid.uuid4()
    token = correlation_id_var.set("corr-failclosed-01")
    owner.execute(f'REVOKE INSERT ON audit.evento FROM "{ROLE}"')
    try:
        with pytest.raises(AuditUnavailableError):
            async with UnitOfWork(db.sessionmaker, AuditContext.system(), spool) as uow:
                await uow.session.execute(
                    text("INSERT INTO app.zz_prueba (id, nombre) VALUES (:i, 'bloqueado')"),
                    {"i": item_id},
                )
                uow.audit(AuditEntry(categoria="PRUEBA", accion="ZZ_CREATED", modulo="ADM",
                                     entidad="zz_prueba", entidad_id=str(item_id)))
                await uow.commit()
    finally:
        owner.execute(f'GRANT INSERT ON audit.evento TO "{ROLE}"')
        correlation_id_var.reset(token)

    # El cambio de negocio NO se persistió.
    assert owner.execute("SELECT count(*) FROM app.zz_prueba WHERE id = %s",
                         (item_id,)).fetchone()[0] == 0
    # Quedó incidente en el spool, sin datos de negocio.
    incident = json.loads((tmp_path / IncidentSpool.FILE).read_text().splitlines()[0])
    assert incident["accion"] == "ZZ_CREATED"
    assert "bloqueado" not in json.dumps(incident)

    # Recuperación: volcado a ops + evento de auditoría.
    assert await spool.flush(db.sessionmaker) == 1
    assert not (tmp_path / IncidentSpool.FILE).exists()
    err = owner.execute(
        "SELECT categoria, severidad FROM ops.registro_error WHERE correlation_id = %s",
        ("corr-failclosed-01",),
    ).fetchone()
    assert err == ("AUDITORIA", "CRITICA")
    assert owner.execute(
        "SELECT count(*) FROM audit.evento WHERE accion = 'OPS_AUDIT_OUTAGE_RECORDED'"
    ).fetchone()[0] >= 1


async def test_successful_unit_of_work_persists_change_and_event(owner, db, tmp_path):
    item_id = uuid.uuid4()
    async with UnitOfWork(db.sessionmaker, AuditContext.system(), IncidentSpool(tmp_path)) as uow:
        await uow.session.execute(
            text("INSERT INTO app.zz_prueba (id, nombre) VALUES (:i, 'ok')"), {"i": item_id}
        )
        uow.audit(AuditEntry(categoria="PRUEBA", accion="ZZ_CREATED", entidad="zz_prueba",
                             entidad_id=str(item_id), valor_nuevo={"nombre": "ok"}))
        await uow.commit()
    assert owner.execute("SELECT nombre FROM app.zz_prueba WHERE id = %s",
                         (item_id,)).fetchone()[0] == "ok"
    ev = owner.execute("SELECT valor_nuevo FROM audit.evento WHERE entidad_id = %s",
                       (str(item_id),)).fetchone()
    assert ev[0] == {"nombre": "ok"}


async def test_business_error_rolls_back_without_audit(owner, db, tmp_path):
    item_id = uuid.uuid4()
    owner.execute("INSERT INTO app.zz_prueba (id, nombre) VALUES (%s, 'dup')", (item_id,))
    with pytest.raises(Exception):  # noqa: B017 - violación de PK
        async with UnitOfWork(db.sessionmaker, AuditContext.system(),
                              IncidentSpool(tmp_path)) as uow:
            await uow.session.execute(
                text("INSERT INTO app.zz_prueba (id, nombre) VALUES (:i, 'dup')"), {"i": item_id}
            )
            uow.audit(AuditEntry(categoria="PRUEBA", accion="ZZ_DUP", entidad_id=str(item_id)))
            await uow.commit()
    assert owner.execute("SELECT count(*) FROM audit.evento WHERE accion = 'ZZ_DUP'"
                         ).fetchone()[0] == 0
    assert not (tmp_path / IncidentSpool.FILE).exists()  # no es un incidente de auditoría


# --------------------------------------------------------------------------- errores (§6)

async def test_record_error_independent_transaction(owner, db):
    token = correlation_id_var.set("corr-error-0001")
    try:
        eid = await record_error(db.sessionmaker, categoria="CRUD", componente="test",
                                 tipo="Prueba", descripcion="fallo password=abc",
                                 diagnostico={"token": "t", "campo": "x"})
    finally:
        correlation_id_var.reset(token)
    row = owner.execute(
        "SELECT descripcion, diagnostico, estado_atencion FROM ops.registro_error WHERE id = %s",
        (eid,),
    ).fetchone()
    assert "abc" not in row[0]
    assert row[1] == {"token": "***", "campo": "x"}
    assert row[2] == "ABIERTO"


def test_unhandled_api_error_is_recorded_with_correlation_id(owner):
    app = create_app()

    @app.get("/api/v1/_t/boom")
    async def boom():
        raise RuntimeError("interno")

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/api/v1/_t/boom")
        ready = client.get("/api/v1/health/ready")
    assert r.status_code == 500
    cid = r.headers["X-Request-ID"]
    assert r.json()["error"]["correlation_id"] == cid
    row = owner.execute(
        "SELECT categoria, tipo FROM ops.registro_error WHERE correlation_id = %s", (cid,)
    ).fetchone()
    assert row == ("INFRAESTRUCTURA", "RuntimeError")
    # Criterio §1: readiness real con migraciones en head.
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"postgres": "ok", "redis": "ok", "migrations": "ok"}
