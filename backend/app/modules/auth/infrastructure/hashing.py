"""Hash de contraseñas con Argon2id (REQ-AUTH-02; PD-02 PROPUESTO).

`dummy_verify` iguala el tiempo de respuesta cuando el usuario no existe o no está activo,
para no permitir enumerar cuentas por tiempo.
"""

import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


@lru_cache
def _hasher() -> PasswordHasher:
    return PasswordHasher()  # parámetros por defecto de argon2-cffi (Argon2id)


@lru_cache
def _dummy_hash() -> str:
    return _hasher().hash(secrets.token_urlsafe(24))


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher().check_needs_rehash(password_hash)


def dummy_verify(password: str) -> None:
    verify_password(_dummy_hash(), password)
