"""Política de contraseñas (REQ-AUTH-03, APROBADA en P §5).

- Mínimo 12 caracteres; mayúscula, minúscula, número y carácter especial.
- No puede coincidir con el usuario de red (APROBADO) ni contenerlo (PROPUESTO).
- Máximo 128 caracteres (PROPUESTO: acota el coste del hash).
- La no reutilización de las últimas 5 se valida contra el historial (servicio).
"""

import secrets
import string

MIN_LENGTH = 12
MAX_LENGTH = 128
_SPECIALS = "!@#$%&*()-_=+[]{};:,.?/"


def password_policy_violations(password: str, usuario_red: str) -> list[str]:
    errors: list[str] = []
    if len(password) < MIN_LENGTH:
        errors.append("MIN_LENGTH")
    if len(password) > MAX_LENGTH:
        errors.append("MAX_LENGTH")
    if not any(c.isupper() for c in password):
        errors.append("UPPERCASE_REQUIRED")
    if not any(c.islower() for c in password):
        errors.append("LOWERCASE_REQUIRED")
    if not any(c.isdigit() for c in password):
        errors.append("DIGIT_REQUIRED")
    if not any(not c.isalnum() and not c.isspace() for c in password):
        errors.append("SPECIAL_REQUIRED")
    if usuario_red and usuario_red.lower() in password.lower():
        errors.append("CONTAINS_USERNAME")
    return errors


def generate_temporary_password(length: int = 16) -> str:
    """Contraseña temporal aleatoria (CSPRNG) que cumple la política."""
    if length < MIN_LENGTH:
        raise ValueError("longitud insuficiente")
    pools = [string.ascii_uppercase, string.ascii_lowercase, string.digits, _SPECIALS]
    chars = [secrets.choice(p) for p in pools]
    alphabet = "".join(pools)
    chars += [secrets.choice(alphabet) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
