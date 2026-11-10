"""Sesiones vivas en Redis (PD-01 APROBADO).

Claves (TTL = inactividad permitida, deslizante solo con actividad real):
    so:sess:{sid}       -> user_id
    so:usess:{user_id}  -> sid vigente (una sesión por usuario)
    so:act:{sid}        -> marca para limitar escrituras de última actividad en BD

Cualquier error de Redis se traduce a ServiceUnavailableError (fail-closed, 503).
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.errors import ServiceUnavailableError

T = TypeVar("T")


def _sess(sid: uuid.UUID) -> str:
    return f"so:sess:{sid}"


def _usess(uid: uuid.UUID) -> str:
    return f"so:usess:{uid}"


def _act(sid: uuid.UUID) -> str:
    return f"so:act:{sid}"


class SessionStore:
    def __init__(self, client: aioredis.Redis, idle_seconds: int) -> None:
        self.client = client
        self.idle = idle_seconds

    async def _safe(self, fn: Callable[[], Awaitable[T]]) -> T:
        try:
            return await fn()
        except (RedisError, OSError) as exc:
            raise ServiceUnavailableError() from exc

    async def ping(self) -> None:
        await self._safe(self.client.ping)

    async def open(self, uid: uuid.UUID, sid: uuid.UUID, previous: uuid.UUID | None) -> None:
        async def run() -> None:
            pipe = self.client.pipeline(transaction=True)
            if previous is not None:
                pipe.delete(_sess(previous), _act(previous))
            pipe.set(_sess(sid), str(uid), ex=self.idle)
            pipe.set(_usess(uid), str(sid), ex=self.idle)
            await pipe.execute()

        await self._safe(run)

    async def close(self, uid: uuid.UUID, sid: uuid.UUID) -> None:
        async def run() -> None:
            pipe = self.client.pipeline(transaction=True)
            pipe.delete(_sess(sid), _act(sid))
            await pipe.execute()
            # Solo borra el puntero de usuario si apunta a esta sesión.
            current = await self.client.get(_usess(uid))
            if current is not None and current.decode() == str(sid):
                await self.client.delete(_usess(uid))

        await self._safe(run)

    async def is_active(self, uid: uuid.UUID, sid: uuid.UUID) -> bool:
        async def run() -> bool:
            owner, current = await self.client.mget(_sess(sid), _usess(uid))
            return (
                owner is not None
                and current is not None
                and owner.decode() == str(uid)
                and current.decode() == str(sid)
            )

        return await self._safe(run)

    async def touch(self, uid: uuid.UUID, sid: uuid.UUID) -> bool:
        """Extiende la ventana de inactividad. Devuelve True si toca persistir actividad en BD."""

        async def run() -> bool:
            pipe = self.client.pipeline(transaction=True)
            pipe.expire(_sess(sid), self.idle)
            pipe.expire(_usess(uid), self.idle)
            pipe.set(_act(sid), "1", ex=60, nx=True)
            _, _, first_in_window = await pipe.execute()
            return bool(first_in_window)

        return await self._safe(run)

    async def remaining_seconds(self, sid: uuid.UUID) -> int:
        ttl = await self._safe(lambda: self.client.ttl(_sess(sid)))
        return max(int(ttl), 0)
