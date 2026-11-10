"""Health checks (Fase 1).

- live: el proceso responde.
- ready: PostgreSQL y Redis alcanzables. Nginx lo bloquea desde fuera; lo usan
  Docker y la red interna. No expone detalles de error (solo ok/fail por dependencia).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import psycopg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Response, status

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["health"])

Check = Callable[[Settings], Awaitable[None]]


async def check_postgres(settings: Settings) -> None:
    conn = await psycopg.AsyncConnection.connect(
        settings.postgres_dsn, connect_timeout=max(1, int(settings.health_timeout_seconds))
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            await cur.fetchone()
    finally:
        await conn.close()


async def check_redis(settings: Settings) -> None:
    client = aioredis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password.get_secret_value(),
        socket_connect_timeout=settings.health_timeout_seconds,
        socket_timeout=settings.health_timeout_seconds,
    )
    try:
        if not await client.ping():
            raise RuntimeError("redis ping failed")
    finally:
        await client.aclose()


def get_checks() -> dict[str, Check]:
    return {"postgres": check_postgres, "redis": check_redis}


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    response: Response,
    settings: Settings = Depends(get_settings),  # noqa: B008
    checks: dict[str, Check] = Depends(get_checks),  # noqa: B008
) -> dict[str, object]:
    async def run(name: str, check: Check) -> tuple[str, bool]:
        try:
            await asyncio.wait_for(check(settings), timeout=settings.health_timeout_seconds + 1)
            return name, True
        except Exception as exc:  # noqa: BLE001 - se registra el tipo, nunca el detalle
            logger.warning("readiness check failed: %s (%s)", name, type(exc).__name__)
            return name, False

    results = dict(await asyncio.gather(*(run(n, c) for n, c in checks.items())))
    ok = all(results.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if ok else "fail",
        "checks": {k: ("ok" if v else "fail") for k, v in results.items()},
    }
