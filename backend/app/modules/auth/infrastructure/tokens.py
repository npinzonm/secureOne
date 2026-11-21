"""Tokens (PD-01 APROBADO).

- Access: JWT HS256 de vida corta con `sid`. `typ` = "access" (completo) o "pwchange"
  (restringido a cambio de contraseña y logout).
- Refresh: valor opaco aleatorio de 256 bits; en BD solo se guarda su SHA-256.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

ISSUER = "secureone"
AUDIENCE = "secureone-api"
ALGORITHM = "HS256"
TokenType = Literal["access", "pwchange"]


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    typ: TokenType


class InvalidTokenError(Exception):
    pass


def issue_access_token(
    secret: str, user_id: uuid.UUID, session_id: uuid.UUID, typ: TokenType, ttl_seconds: int
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": typ,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(secret: str, token: str) -> AccessClaims:
    try:
        data = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "sid", "typ", "iss", "aud"]},
        )
        typ = data["typ"]
        if typ not in ("access", "pwchange"):
            raise InvalidTokenError("typ")
        return AccessClaims(uuid.UUID(data["sub"]), uuid.UUID(data["sid"]), typ)
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(type(exc).__name__) from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()
