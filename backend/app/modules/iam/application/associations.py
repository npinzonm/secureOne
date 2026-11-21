"""Asociaciones históricas (perfil_rol, rol_permiso, usuario_modulo): se activan/inactivan,
nunca se borran (regla 11). Devuelve el conjunto activo antes y después para auditoría."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_TABLES = {
    "perfil_rol": ("perfil_id", "rol_id", "rol", "codigo"),
    "rol_permiso": ("rol_id", "permiso_id", "permiso", "codigo"),
    "usuario_modulo": ("usuario_id", "modulo_id", "modulo", "codigo"),
}


async def active_codes(s: AsyncSession, table: str, owner_id: uuid.UUID) -> list[str]:
    left, right, ref, code = _TABLES[table]
    rows = await s.execute(text(
        f"SELECT x.{code} FROM app.{table} a JOIN app.{ref} x ON x.id = a.{right} "  # noqa: S608
        f"WHERE a.{left} = :o AND a.estado = 'ACTIVO' ORDER BY 1"), {"o": owner_id})
    return list(rows.scalars().all())


async def set_active(
    s: AsyncSession, table: str, owner_id: uuid.UUID, desired: dict[str, uuid.UUID],
    actor: uuid.UUID | None,
) -> tuple[list[str], list[str]]:
    """Deja activas exactamente las asociaciones `desired` (código → id).

    Devuelve los códigos activos (antes, después).
    """
    left, right, _, _ = _TABLES[table]
    before = await active_codes(s, table, owner_id)
    ids = list(desired.values())
    await s.execute(text(
        f"UPDATE app.{table} SET estado = 'INACTIVO', inhabilitado_en = now() "  # noqa: S608
        f"WHERE {left} = :o AND estado = 'ACTIVO' AND NOT ({right} = ANY(:ids))"),
        {"o": owner_id, "ids": ids})
    for rid in ids:
        await s.execute(text(
            f"INSERT INTO app.{table} ({left}, {right}, asignado_por) VALUES (:o, :r, :a) "  # noqa: S608
            f"ON CONFLICT ({left}, {right}) DO UPDATE SET estado = 'ACTIVO', "
            f"inhabilitado_en = NULL, asignado_en = CASE WHEN app.{table}.estado = 'ACTIVO' "
            f"THEN app.{table}.asignado_en ELSE now() END, asignado_por = CASE WHEN "
            f"app.{table}.estado = 'ACTIVO' THEN app.{table}.asignado_por ELSE :a END"),
            {"o": owner_id, "r": rid, "a": actor})
    after = await active_codes(s, table, owner_id)
    return before, after
