"""Worker en segundo plano (contenedor `worker`).

Ciclo:
  - cada `worker_poll_seconds`: entregas de notificaciones pendientes (outbox);
  - cada ciclo: ejecuciones TH pendientes (retirados primero) y luego entregas;
  - cada 60 s: spool de auditoría, sesiones abandonadas y alerta de archivo diario TH;
  - heartbeat en /tmp/worker-heartbeat para el health check.
Errores de un ciclo se registran y el worker continúa (nunca se detiene por un fallo puntual).
"""

import asyncio
import logging
import signal
import time
from pathlib import Path

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.db import Database
from app.core.logging import configure_logging
from app.kernel.audit import IncidentSpool
from app.modules.auth.application.maintenance import close_abandoned_sessions
from app.modules.auth.infrastructure.session_store import SessionStore
from app.modules.notifications.application.delivery import SmtpSender, process_batch
from app.modules.th.application.intake import check_missing_daily_file
from app.modules.th.application.processor import process_next

logger = logging.getLogger("secureone.worker")
HEARTBEAT = Path("/tmp/worker-heartbeat")  # noqa: S108 - tmpfs del contenedor
MAINTENANCE_EVERY = 60.0


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    db = Database(settings.sqlalchemy_url, pool_size=2, max_overflow=1)
    rds = aioredis.Redis(host=settings.redis_host, port=settings.redis_port,
                         password=settings.redis_password.get_secret_value(),
                         socket_connect_timeout=2, socket_timeout=2)
    store = SessionStore(rds, settings.session_idle_seconds)
    spool = IncidentSpool(settings.spool_dir)
    sender = SmtpSender(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    last_maintenance = 0.0
    logger.info("worker iniciado")
    try:
        while not stop.is_set():
            try:
                # TH primero (retirados antes que activa); hasta 5 ejecuciones por ciclo.
                for _ in range(5):
                    if not await process_next(db.sessionmaker, spool):
                        break
                r = await process_batch(db.sessionmaker, sender)
                if r.enviadas or r.reintentos or r.agotadas:
                    logger.info("entregas: %d enviadas, %d reintentos, %d agotadas",
                                r.enviadas, r.reintentos, r.agotadas)
                if time.monotonic() - last_maintenance >= MAINTENANCE_EVERY:
                    n = await spool.flush(db.sessionmaker)
                    c = await close_abandoned_sessions(db.sessionmaker, store, spool,
                                                       settings.session_idle_seconds)
                    await check_missing_daily_file(db.sessionmaker, spool)
                    if n or c:
                        logger.info("mantenimiento: %d incidentes volcados, %d sesiones cerradas",
                                    n, c)
                    last_maintenance = time.monotonic()
                HEARTBEAT.write_text(str(time.time()))
            except Exception as exc:  # noqa: BLE001
                logger.error("ciclo del worker falló (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                pass
    finally:
        await rds.aclose()
        await db.dispose()
        logger.info("worker detenido")


def healthcheck(max_age: float = 60.0) -> int:
    try:
        return 0 if time.time() - float(HEARTBEAT.read_text()) < max_age else 1
    except (OSError, ValueError):
        return 1


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "healthcheck":
        sys.exit(healthcheck())
    asyncio.run(run())
