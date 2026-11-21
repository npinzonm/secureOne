"""Identificadores de usuario (REQ-USER-04, REQ-AUTH-01).

Usuario de red: se normaliza (trim + minúsculas) y debe tener 8 caracteres alternados
letra/número. Lectura literal de P §6.1 sin fijar el carácter inicial (PD-07 pendiente):
se aceptan `a1b2c3d4` y `1a2b3c4d`. Debe coincidir con el CHECK de la migración 0002.
"""

import re

USUARIO_RED_RE = re.compile(r"^([a-z][0-9]){4}$|^([0-9][a-z]){4}$")
IDENTIFICACION_RE = re.compile(r"^[A-Za-z0-9-]{3,20}$")


def normalize_usuario_red(value: str) -> str:
    return value.strip().lower()


def is_valid_usuario_red(normalized: str) -> bool:
    return bool(USUARIO_RED_RE.match(normalized))


def is_valid_identificacion(value: str) -> bool:
    return bool(IDENTIFICACION_RE.match(value))

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def is_valid_email(value: str) -> bool:
    return len(value) <= 150 and bool(EMAIL_RE.match(value))
