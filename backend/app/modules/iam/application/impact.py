"""Impacto previo de cambios en roles/permisos (REQ-IAM-09, ESP-ADM-IAM R6).

Flujo:
  1. POST .../impact  → {perfiles, usuarios, ..., confirm_impact_token}
  2. PUT/POST ...     → exige `confirm_impact_token`; se recalcula el impacto y debe coincidir.

El token es un HMAC sin estado (secreto JWT) sobre: operación, objetivo, cambio solicitado e
impacto calculado, con vencimiento (10 min, PROPUESTO). Si el impacto cambió entre la
consulta y la confirmación → 409; si falta o no corresponde a la operación → 422/409.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError

TOKEN_TTL_SECONDS = 600
MAX_LISTED_USERS = 200


@dataclass(frozen=True)
class Impact:
    perfiles: list[str]
    usuarios: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "perfiles_afectados": self.perfiles,
            "usuarios_afectados": len(self.usuarios),
            "usuarios": self.usuarios[:MAX_LISTED_USERS],
        }


class ImpactConfirmationRequiredError(BusinessRuleError):
    code = "IMPACT_CONFIRMATION_REQUIRED"
    message = "Debe consultar y confirmar el impacto antes de aplicar este cambio."


class ImpactChangedError(ConflictError):
    code = "IMPACT_CHANGED"
    message = "El impacto cambió o la confirmación no corresponde. Consulte el impacto de nuevo."


def _digest(secret: str, operation: str, target: uuid.UUID, change: Any, impact: Impact,
            exp: int) -> str:
    material = json.dumps(
        {"op": operation, "t": str(target), "c": change, "p": impact.perfiles,
         "u": impact.usuarios, "exp": exp},
        sort_keys=True, default=str,
    ).encode()
    mac = hmac.new(secret.encode(), material, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def issue_token(secret: str, operation: str, target: uuid.UUID, change: Any,
                impact: Impact) -> str:
    exp = int(time.time()) + TOKEN_TTL_SECONDS
    return f"{exp}.{_digest(secret, operation, target, change, impact, exp)}"


def verify_token(secret: str, token: str | None, operation: str, target: uuid.UUID,
                 change: Any, impact: Impact) -> None:
    if not token:
        raise ImpactConfirmationRequiredError()
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except ValueError as exc:
        raise ImpactChangedError() from exc
    if exp < time.time():
        raise ImpactChangedError("La confirmación de impacto venció. Consulte el impacto de nuevo.")
    expected = _digest(secret, operation, target, change, impact, exp)
    if not hmac.compare_digest(expected, sig):
        raise ImpactChangedError()


async def _impact_for_profiles(s: AsyncSession, perfil_sql: str, params: dict) -> Impact:
    perfiles = (await s.execute(text(
        f"SELECT DISTINCT pf.codigo FROM app.perfil pf WHERE pf.estado = 'ACTIVO' "  # noqa: S608
        f"AND pf.id IN ({perfil_sql}) ORDER BY 1"), params)).scalars().all()
    usuarios = (await s.execute(text(
        f"SELECT u.usuario_red FROM app.usuario u JOIN app.perfil pf ON pf.id = u.perfil_id "  # noqa: S608
        f"WHERE u.estado = 'ACTIVO' AND pf.estado = 'ACTIVO' AND pf.id IN ({perfil_sql}) "
        f"ORDER BY 1"), params)).scalars().all()
    return Impact(list(perfiles), list(usuarios))


async def impact_of_role(s: AsyncSession, rol_id: uuid.UUID) -> Impact:
    """Perfiles activos que tienen el rol (asociación activa) y sus usuarios activos."""
    return await _impact_for_profiles(
        s, "SELECT perfil_id FROM app.perfil_rol WHERE rol_id = :r AND estado = 'ACTIVO'",
        {"r": rol_id},
    )


async def impact_of_permission(s: AsyncSession, permiso_id: uuid.UUID) -> Impact:
    return await _impact_for_profiles(
        s,
        "SELECT pr.perfil_id FROM app.perfil_rol pr JOIN app.rol r ON r.id = pr.rol_id "
        "JOIN app.rol_permiso rp ON rp.rol_id = r.id WHERE rp.permiso_id = :p "
        "AND rp.estado = 'ACTIVO' AND pr.estado = 'ACTIVO' AND r.estado = 'ACTIVO'",
        {"p": permiso_id},
    )


async def impact_of_profile(s: AsyncSession, perfil_id: uuid.UUID) -> Impact:
    return await _impact_for_profiles(s, "SELECT CAST(:pf AS uuid)", {"pf": perfil_id})
