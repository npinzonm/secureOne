"""Validaciones de usuario compartidas por la creación (Fase 5) y la aprobación (Fase 6)."""

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, NotFoundError


async def load_user(s: AsyncSession, uid: uuid.UUID) -> dict[str, Any]:
    row = (await s.execute(text(
        "SELECT u.*, pf.codigo AS perfil FROM app.usuario u JOIN app.perfil pf "
        "ON pf.id = u.perfil_id WHERE u.id = :u FOR UPDATE OF u"), {"u": uid})).mappings().first()
    if row is None:
        raise NotFoundError()
    return dict(row)


async def active_id(s: AsyncSession, sql: str, value: Any, label: str) -> uuid.UUID:
    row = (await s.execute(text(sql), {"v": value})).first()
    if row is None:
        raise BusinessRuleError(f"{label} no existe.")
    if row[1] != "ACTIVO":
        raise BusinessRuleError(f"{label} está inactivo.")
    return row[0]


async def validate_org(s: AsyncSession, g: uuid.UUID, a: uuid.UUID, c: uuid.UUID) -> None:
    await active_id(s, "SELECT id, estado FROM app.gerencia WHERE id = :v", g, "La gerencia")
    await active_id(s, "SELECT id, estado FROM app.cargo WHERE id = :v", c, "El cargo")
    area = (await s.execute(text("SELECT estado, gerencia_id FROM app.area WHERE id = :a"),
                            {"a": a})).first()
    if area is None or area[0] != "ACTIVO":
        raise BusinessRuleError("El área no existe o está inactiva.")
    if area[1] != g:  # REQ-USER-06
        raise BusinessRuleError("El área no pertenece a la gerencia seleccionada.")


async def module_codes(s: AsyncSession, codes: list[str]) -> list[str]:
    codes = sorted(set(codes))
    rows = (await s.execute(text("SELECT codigo, estado FROM app.modulo WHERE codigo = ANY(:c)"),
                            {"c": codes})).all()
    found = {r[0]: r[1] for r in rows}
    bad = [c for c in codes if found.get(c) != "ACTIVO"]
    if bad:
        raise BusinessRuleError("Hay módulos inexistentes o inactivos.", details={"modulos": bad})
    return codes


async def current_modules(s: AsyncSession, uid: uuid.UUID) -> list[str]:
    return list((await s.execute(text(
        "SELECT m.codigo FROM app.usuario_modulo um JOIN app.modulo m ON m.id = um.modulo_id "
        "WHERE um.usuario_id = :u AND um.estado = 'ACTIVO' ORDER BY 1"), {"u": uid})).scalars())


async def active_admins(s: AsyncSession) -> int:
    return (await s.execute(text(
        "SELECT count(*) FROM app.usuario u JOIN app.perfil pf ON pf.id = u.perfil_id "
        "WHERE pf.codigo = 'ADMINISTRADOR' AND u.estado = 'ACTIVO'"))).scalar_one()


async def record_state(
    s: AsyncSession, uid: uuid.UUID, antes: str | None, despues: str, motivo: str,
    actor: uuid.UUID | None, solicitud_id: uuid.UUID | None,
) -> None:
    """REQ-USER-08: historial de estados con actor, fecha y motivo (solo inserción)."""
    from app.core.ids import uuid7

    await s.execute(text(
        "INSERT INTO app.usuario_estado_historial (id, usuario_id, estado_anterior, "
        "estado_nuevo, motivo, actor_id, solicitud_id) VALUES (:id, :u, :a, :d, :m, :ac, :s)"),
        {"id": uuid7(), "u": uid, "a": antes, "d": despues, "m": motivo, "ac": actor,
         "s": solicitud_id})
