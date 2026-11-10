"""Unitarias de seguridad de autenticación: política, identificadores, hash y tokens."""

import time
import uuid

import jwt
import pytest

from app.modules.auth.domain.password_policy import (
    generate_temporary_password,
    password_policy_violations,
)
from app.modules.auth.infrastructure.hashing import hash_password, verify_password
from app.modules.auth.infrastructure.tokens import (
    InvalidTokenError,
    decode_access_token,
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
)
from app.modules.users.domain.identifiers import is_valid_usuario_red, normalize_usuario_red

SECRET = "unit-test-secret-0123456789-0123456789"


@pytest.mark.parametrize(
    ("pwd", "expected"),
    [
        ("Corta1!", {"MIN_LENGTH"}),
        ("sinmayusculas1!", {"UPPERCASE_REQUIRED"}),
        ("SINMINUSCULAS1!", {"LOWERCASE_REQUIRED"}),
        ("SinNumeros!!!!", {"DIGIT_REQUIRED"}),
        ("SinEspecial1234", {"SPECIAL_REQUIRED"}),
        ("Xa1b2c3d4!Valida", {"CONTAINS_USERNAME"}),
        ("A" * 120 + "a1!" + "x" * 10, {"MAX_LENGTH"}),
        ("Correcta#2026xyz", set()),
    ],
)
def test_password_policy(pwd, expected):
    assert set(password_policy_violations(pwd, "a1b2c3d4")) == expected


def test_password_equal_to_username_case_insensitive_is_rejected():
    assert "CONTAINS_USERNAME" in password_policy_violations("A1B2C3D4", "a1b2c3d4")


def test_temporary_passwords_are_random_and_compliant():
    pwds = {generate_temporary_password() for _ in range(200)}
    assert len(pwds) == 200
    assert all(password_policy_violations(p, "z9y8x7w6") == [] for p in pwds)


@pytest.mark.parametrize(
    ("raw", "valid"),
    [
        ("  A1B2C3D4 ", True),   # se normaliza
        ("1a2b3c4d", True),      # lectura literal de "alternados" (PD-07 pendiente)
        ("a1b2c3d", False),
        ("a1b2c3d4e", False),
        ("aa11bb22", False),
        ("a1b2c3dñ", False),
        ("a1b2-3d4", False),
    ],
)
def test_usuario_red(raw, valid):
    assert is_valid_usuario_red(normalize_usuario_red(raw)) is valid


def test_argon2id_hash_and_verify():
    h = hash_password("Correcta#2026xyz")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Correcta#2026xyz")
    assert not verify_password(h, "Incorrecta#2026")
    assert not verify_password("no-es-un-hash", "x")


def test_access_token_roundtrip_and_types():
    uid, sid = uuid.uuid4(), uuid.uuid4()
    for typ in ("access", "pwchange"):
        c = decode_access_token(SECRET, issue_access_token(SECRET, uid, sid, typ, 60))
        assert (c.user_id, c.session_id, c.typ) == (uid, sid, typ)


def test_access_token_rejections():
    uid, sid = uuid.uuid4(), uuid.uuid4()
    good = issue_access_token(SECRET, uid, sid, "access", 60)
    with pytest.raises(InvalidTokenError):
        decode_access_token("otro-secreto-0123456789-0123456789", good)
    expired = issue_access_token(SECRET, uid, sid, "access", -1)
    with pytest.raises(InvalidTokenError):
        decode_access_token(SECRET, expired)
    unsigned = jwt.encode({"sub": str(uid), "sid": str(sid), "typ": "access",
                           "iat": int(time.time()), "exp": int(time.time()) + 60,
                           "iss": "secureone", "aud": "secureone-api"}, key="", algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_access_token(SECRET, unsigned)
    bad_typ = jwt.encode({"sub": str(uid), "sid": str(sid), "typ": "admin",
                          "iat": int(time.time()), "exp": int(time.time()) + 60,
                          "iss": "secureone", "aud": "secureone-api"}, SECRET, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(SECRET, bad_typ)
    tampered = good[:-2] + ("A" if good[-2] != "A" else "B") + good[-1]
    with pytest.raises(InvalidTokenError):
        decode_access_token(SECRET, tampered)


def test_refresh_tokens_are_random_and_only_hash_is_stored():
    a, b = new_refresh_token(), new_refresh_token()
    assert a != b and len(a) >= 43
    assert hash_refresh_token(a) != hash_refresh_token(b)
    assert len(hash_refresh_token(a)) == 32


def test_client_ip_is_validated():
    from types import SimpleNamespace

    from app.modules.auth.api.dependencies import client_ip

    def req(header, host):
        return SimpleNamespace(headers={"x-real-ip": header} if header else {},
                               client=SimpleNamespace(host=host) if host else None)

    assert client_ip(req("10.1.2.3", "172.18.0.5")) == "10.1.2.3"
    assert client_ip(req("<script>", "172.18.0.5")) == "172.18.0.5"
    assert client_ip(req(None, "testclient")) is None
    assert client_ip(req("::1", None)) == "::1"
