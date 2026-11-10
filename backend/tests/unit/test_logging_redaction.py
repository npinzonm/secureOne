"""REQ-ERR-03 / T-SEC-18 (base): los logs no contienen secretos."""

import json
import logging

from app.core.config import Settings
from app.core.logging import REDACTED, JsonFormatter, redact


def test_redact_nested_sensitive_keys():
    data = {
        "user": "a1b2c3d4",
        "password": "x",
        "nested": {"refresh_token": "y"},
        "l": [{"Cookie": "z"}],
    }
    out = redact(data)
    assert out == {"user": "a1b2c3d4", "password": REDACTED,
                   "nested": {"refresh_token": REDACTED}, "l": [{"Cookie": REDACTED}]}


def test_redact_inline_strings():
    assert redact("login failed password=Secreto123!") == f"login failed password={REDACTED}"
    assert "abc.def" not in str(redact("Authorization: abc.def"))


def test_formatter_redacts_message():
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "token=%s", ("eyJhbGci",), None)
    line = json.loads(JsonFormatter().format(rec))
    assert "eyJhbGci" not in line["msg"]


def test_settings_secrets_not_in_repr():
    s = Settings(postgres_db="d", postgres_user="u", postgres_password="p@ss/w0rd",
                 redis_password="r3dis")
    assert "p@ss/w0rd" not in repr(s)
    assert "r3dis" not in repr(s)
    assert "p%40ss%2Fw0rd" in s.postgres_dsn  # contraseña escapada correctamente en el DSN
