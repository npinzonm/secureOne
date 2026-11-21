"""Unitarias Fase 7: Excel seguro, plantillas de notificación, backoff y heartbeat."""

import io
import time
import uuid
from datetime import UTC, datetime

from openpyxl import load_workbook

from app import worker
from app.core.excel import build_xlsx, safe_cell
from app.modules.notifications.application.delivery import BACKOFF_SECONDS, MAX_ATTEMPTS
from app.modules.notifications.application.outbox import render


def test_formula_injection_is_neutralized():
    for bad in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\t=x"):
        assert safe_cell(bad).startswith("'")
    assert safe_cell("Normal") == "Normal"
    assert safe_cell(5) == 5 and safe_cell(None) is None
    assert safe_cell(uuid.UUID(int=1)) == "00000000-0000-0000-0000-000000000001"
    assert safe_cell(datetime(2026, 1, 1, tzinfo=UTC)).tzinfo is None
    assert safe_cell({"a": "=x"}).startswith("{")


def test_build_xlsx_roundtrip():
    data = build_xlsx("hoja", ["a", "b"], [["=HYPERLINK(1)", 2], ["x", None]])
    ws = load_workbook(io.BytesIO(data)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("a", "b")
    assert rows[1][0] == "'=HYPERLINK(1)" and rows[1][1] == 2


def test_render_is_safe_and_tolerates_missing_keys():
    out = render("Solicitud #{numero} de {actor} sobre {usuario_objetivo}",
                 {"numero": 7, "actor": None})
    assert out == "Solicitud #7 de - sobre -"
    assert "secreto" not in render("{token}", {"token": "secreto"})
    assert len(render("{x}", {"x": "y" * 1000})) == 200


def test_backoff_policy():
    assert BACKOFF_SECONDS == (60, 300, 900, 3600) and MAX_ATTEMPTS == 4


def test_worker_healthcheck(tmp_path, monkeypatch):
    hb = tmp_path / "hb"
    monkeypatch.setattr(worker, "HEARTBEAT", hb)
    assert worker.healthcheck() == 1
    hb.write_text(str(time.time()))
    assert worker.healthcheck() == 0
    hb.write_text(str(time.time() - 120))
    assert worker.healthcheck() == 1
