"""Pruebas unitarias del kernel: ids, saneamiento de auditoría y UnitOfWork fail-closed."""

import json
import uuid

import pytest
from sqlalchemy.exc import OperationalError

from app.core.errors import AuditUnavailableError
from app.core.ids import uuid7
from app.core.logging import REDACTED, correlation_id_var
from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool, build_audit_row
from app.kernel.unit_of_work import MissingAuditError, UnitOfWork


def test_uuid7_version_variant_and_order():
    ids = [uuid7() for _ in range(50)]
    assert all(i.version == 7 for i in ids)
    assert all(i.variant == uuid.RFC_4122 for i in ids)
    assert len(set(ids)) == 50
    # El prefijo de 48 bits (milisegundos) nunca decrece.
    ms = [i.int >> 80 for i in ids]
    assert ms == sorted(ms)


def test_audit_row_masks_sensitive_values_and_carries_correlation():
    token = correlation_id_var.set("corr-12345678")
    try:
        row = build_audit_row(
            AuditEntry(
                categoria="USUARIOS",
                accion="USR_UPDATED",
                valor_anterior={"correo": "a@x.co", "password_hash": "$argon2id$..."},
                valor_nuevo={"correo": "b@x.co", "refresh_token": "abc"},
                detalle={"nota": "token=xyz"},
            ),
            AuditContext(actor_usuario_red="a1b2c3d4", ip_origen="10.0.0.1"),
        )
    finally:
        correlation_id_var.reset(token)
    assert row["valor_anterior"] == {"correo": "a@x.co", "password_hash": REDACTED}
    assert row["valor_nuevo"]["refresh_token"] == REDACTED
    assert "xyz" not in json.dumps(row["detalle"])
    assert row["correlation_id"] == "corr-12345678"
    assert row["id"].version == 7
    # El cliente nunca fija seq, fecha ni hash: los calcula la BD.
    assert not {"seq", "ocurrido_en", "hash", "hash_previo"} & row.keys()


class FakeSession:
    def __init__(self, fail_on_execute: bool = False) -> None:
        self.fail_on_execute = fail_on_execute
        self.calls: list[str] = []

    async def begin(self):
        self.calls.append("begin")

    async def flush(self):
        self.calls.append("flush")

    async def execute(self, _stmt):
        self.calls.append("execute")
        if self.fail_on_execute:
            raise OperationalError("INSERT", {}, Exception("permission denied"))

    async def commit(self):
        self.calls.append("commit")

    async def rollback(self):
        self.calls.append("rollback")

    async def close(self):
        self.calls.append("close")


async def test_commit_without_audit_is_rejected(tmp_path):
    session = FakeSession()
    with pytest.raises(MissingAuditError):
        async with UnitOfWork(lambda: session, AuditContext(), IncidentSpool(tmp_path)) as uow:
            await uow.commit()
    assert "commit" not in session.calls
    assert "rollback" in session.calls


async def test_audit_failure_is_fail_closed(tmp_path):
    session = FakeSession(fail_on_execute=True)
    spool = IncidentSpool(tmp_path)
    with pytest.raises(AuditUnavailableError) as exc_info:
        async with UnitOfWork(lambda: session, AuditContext(), spool) as uow:
            uow.audit(AuditEntry(categoria="USUARIOS", accion="USR_CREATED", modulo="ADM"))
            await uow.commit()
    assert exc_info.value.status_code == 503
    assert "commit" not in session.calls
    assert "rollback" in session.calls
    lines = (tmp_path / IncidentSpool.FILE).read_text().splitlines()
    assert len(lines) == 1
    incident = json.loads(lines[0])
    assert incident["accion"] == "USR_CREATED"
    assert incident["error_type"] == "OperationalError"


async def test_successful_commit_writes_audit_then_commits(tmp_path):
    session = FakeSession()
    async with UnitOfWork(lambda: session, AuditContext(), IncidentSpool(tmp_path)) as uow:
        uow.audit(AuditEntry(categoria="X", accion="Y"))
        await uow.commit()
    assert session.calls == ["begin", "flush", "execute", "commit", "close"]
