"""Acceso a datos de autenticación (SQL explícito, rol de runtime).

Nota de modularidad: `auth` lee `app.usuario`/`app.perfil` (propiedad de users/iam) mediante
esta capa de lectura acotada; no modifica otros datos de usuario que no sean de sesión/acceso.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7


@dataclass(frozen=True)
class LoginRow:
    user_id: uuid.UUID
    usuario_red: str
    estado: str
    password_hash: str
    debe_cambiar: bool
    intentos_fallidos: int
    bloqueado_hasta: datetime | None


async def get_for_login(s: AsyncSession, usuario_red: str) -> LoginRow | None:
    row = (
        await s.execute(
            text(
                """
                SELECT u.id, u.usuario_red, u.estado, c.password_hash, c.debe_cambiar,
                       c.intentos_fallidos, c.bloqueado_hasta
                  FROM app.usuario u JOIN app.credencial c ON c.usuario_id = u.id
                 WHERE u.usuario_red = :red
                   FOR UPDATE OF c
                """
            ),
            {"red": usuario_red},
        )
    ).first()
    return LoginRow(*row) if row else None


async def register_failure(
    s: AsyncSession, uid: uuid.UUID, attempts: int, locked_until: datetime | None
) -> None:
    await s.execute(
        text(
            "UPDATE app.credencial SET intentos_fallidos = :n, bloqueado_hasta = :b "
            "WHERE usuario_id = :u"
        ),
        {"n": attempts, "b": locked_until, "u": uid},
    )


async def reset_failures(s: AsyncSession, uid: uuid.UUID, new_hash: str | None) -> None:
    await s.execute(
        text(
            "UPDATE app.credencial SET intentos_fallidos = 0, bloqueado_hasta = NULL, "
            "password_hash = COALESCE(:h, password_hash) WHERE usuario_id = :u"
        ),
        {"h": new_hash, "u": uid},
    )


async def close_open_session(s: AsyncSession, uid: uuid.UUID, motivo: str) -> uuid.UUID | None:
    sid = (
        await s.execute(
            text(
                "UPDATE app.sesion SET finalizada_en = now(), motivo_fin = :m "
                "WHERE usuario_id = :u AND finalizada_en IS NULL RETURNING id"
            ),
            {"m": motivo, "u": uid},
        )
    ).scalar_one_or_none()
    if sid is not None:
        await revoke_session_tokens(s, sid)
    return sid


async def close_session(s: AsyncSession, sid: uuid.UUID, motivo: str) -> bool:
    closed = (
        await s.execute(
            text(
                "UPDATE app.sesion SET finalizada_en = now(), motivo_fin = :m "
                "WHERE id = :s AND finalizada_en IS NULL RETURNING id"
            ),
            {"m": motivo, "s": sid},
        )
    ).scalar_one_or_none()
    await revoke_session_tokens(s, sid)
    return closed is not None


async def revoke_session_tokens(s: AsyncSession, sid: uuid.UUID) -> None:
    await s.execute(
        text(
            "UPDATE app.refresh_token SET revocado_en = now() "
            "WHERE sesion_id = :s AND revocado_en IS NULL"
        ),
        {"s": sid},
    )


async def create_session(
    s: AsyncSession, uid: uuid.UUID, restricted: bool, ip: str | None, ua: str | None
) -> uuid.UUID:
    sid = uuid7()
    await s.execute(
        text(
            "INSERT INTO app.sesion (id, usuario_id, restringida, ip, user_agent) "
            "VALUES (:id, :u, :r, CAST(:ip AS inet), :ua)"
        ),
        {"id": sid, "u": uid, "r": restricted, "ip": ip, "ua": (ua or None) and ua[:512]},
    )
    await s.execute(
        text(
            "UPDATE app.usuario SET ultimo_ingreso = now(), ultima_actividad = now() "
            "WHERE id = :u"
        ),
        {"u": uid},
    )
    return sid


async def insert_refresh(
    s: AsyncSession, sid: uuid.UUID, family: uuid.UUID, token_hash: bytes
) -> uuid.UUID:
    rid = uuid7()
    await s.execute(
        text(
            "INSERT INTO app.refresh_token (id, sesion_id, familia_id, token_hash) "
            "VALUES (:id, :s, :f, :h)"
        ),
        {"id": rid, "s": sid, "f": family, "h": token_hash},
    )
    return rid


@dataclass(frozen=True)
class RefreshRow:
    id: uuid.UUID
    sesion_id: uuid.UUID
    familia_id: uuid.UUID
    usado_en: datetime | None
    revocado_en: datetime | None
    usuario_id: uuid.UUID
    sesion_finalizada: datetime | None
    usuario_estado: str


async def get_refresh_for_update(s: AsyncSession, token_hash: bytes) -> RefreshRow | None:
    row = (
        await s.execute(
            text(
                """
                SELECT rt.id, rt.sesion_id, rt.familia_id, rt.usado_en, rt.revocado_en,
                       se.usuario_id, se.finalizada_en, u.estado
                  FROM app.refresh_token rt
                  JOIN app.sesion se ON se.id = rt.sesion_id
                  JOIN app.usuario u ON u.id = se.usuario_id
                 WHERE rt.token_hash = :h
                   FOR UPDATE OF rt
                """
            ),
            {"h": token_hash},
        )
    ).first()
    return RefreshRow(*row) if row else None


async def mark_refresh_used(s: AsyncSession, rid: uuid.UUID, replaced_by: uuid.UUID) -> None:
    await s.execute(
        text("UPDATE app.refresh_token SET usado_en = now(), reemplazado_por = :n WHERE id = :i"),
        {"n": replaced_by, "i": rid},
    )


async def get_user_state(s: AsyncSession, uid: uuid.UUID) -> tuple[str, str] | None:
    row = (
        await s.execute(
            text("SELECT estado, usuario_red FROM app.usuario WHERE id = :u"), {"u": uid}
        )
    ).first()
    return (row[0], row[1]) if row else None


async def session_is_open(s: AsyncSession, sid: uuid.UUID) -> bool:
    return (
        await s.execute(
            text("SELECT 1 FROM app.sesion WHERE id = :s AND finalizada_en IS NULL"), {"s": sid}
        )
    ).first() is not None


async def touch_activity(s: AsyncSession, uid: uuid.UUID, sid: uuid.UUID) -> None:
    await s.execute(
        text("UPDATE app.sesion SET ultima_actividad = now() WHERE id = :s"), {"s": sid}
    )
    await s.execute(
        text("UPDATE app.usuario SET ultima_actividad = now() WHERE id = :u"), {"u": uid}
    )


async def get_credential(s: AsyncSession, uid: uuid.UUID) -> tuple[str, str] | None:
    row = (
        await s.execute(
            text(
                "SELECT c.password_hash, u.usuario_red FROM app.credencial c "
                "JOIN app.usuario u ON u.id = c.usuario_id WHERE c.usuario_id = :u "
                "FOR UPDATE OF c"
            ),
            {"u": uid},
        )
    ).first()
    return (row[0], row[1]) if row else None


async def recent_password_hashes(s: AsyncSession, uid: uuid.UUID, limit: int) -> list[str]:
    rows = await s.execute(
        text(
            "SELECT password_hash FROM app.historial_contrasena WHERE usuario_id = :u "
            "ORDER BY creada_en DESC, id DESC LIMIT :n"
        ),
        {"u": uid, "n": limit},
    )
    return [r[0] for r in rows]


async def set_password(
    s: AsyncSession, uid: uuid.UUID, new_hash: str, must_change: bool, keep: int
) -> None:
    await s.execute(
        text(
            "UPDATE app.credencial SET password_hash = :h, debe_cambiar = :m, "
            "cambiada_en = now(), intentos_fallidos = 0, bloqueado_hasta = NULL "
            "WHERE usuario_id = :u"
        ),
        {"h": new_hash, "m": must_change, "u": uid},
    )
    await add_password_history(s, uid, new_hash, keep)


async def add_password_history(s: AsyncSession, uid: uuid.UUID, new_hash: str, keep: int) -> None:
    await s.execute(
        text(
            "INSERT INTO app.historial_contrasena (id, usuario_id, password_hash) "
            "VALUES (:id, :u, :h)"
        ),
        {"id": uuid7(), "u": uid, "h": new_hash},
    )
    # Minimización (PD-02): solo se conservan las últimas `keep`.
    await s.execute(
        text(
            """
            DELETE FROM app.historial_contrasena
             WHERE usuario_id = :u AND id NOT IN (
               SELECT id FROM app.historial_contrasena WHERE usuario_id = :u
                ORDER BY creada_en DESC, id DESC LIMIT :k)
            """
        ),
        {"u": uid, "k": keep},
    )


async def get_me(s: AsyncSession, uid: uuid.UUID) -> dict[str, Any] | None:
    row = (
        await s.execute(
            text(
                """
                SELECT u.usuario_red, u.nombre, u.primer_apellido, u.segundo_apellido,
                       u.correo, p.codigo AS perfil_codigo, p.nombre AS perfil_nombre,
                       u.ultimo_ingreso
                  FROM app.usuario u JOIN app.perfil p ON p.id = u.perfil_id
                 WHERE u.id = :u
                """
            ),
            {"u": uid},
        )
    ).mappings().first()
    return dict(row) if row else None
