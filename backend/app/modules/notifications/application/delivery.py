"""Entrega de notificaciones (worker; REQ-NOT-03/04, D-NOT-001).

- Cada entrega se procesa en su propia transacción, tomada con FOR UPDATE SKIP LOCKED
  (varios workers no duplican envíos).
- BANDEJA: publicar = marcar ENVIADA (visible en la bandeja interna).
- CORREO: SMTP. Si falla: reintentos con backoff 1, 5, 15, 60 min (PD-11, PROPUESTO).
  Agotados → AGOTADA + alerta técnica en bandeja + ops.registro_error. La operación que originó
  la notificación nunca se ve afectada.
"""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.kernel.error_registry import record_error
from app.modules.notifications.application.outbox import generate

logger = logging.getLogger(__name__)
BACKOFF_SECONDS = (60, 300, 900, 3600)
MAX_ATTEMPTS = len(BACKOFF_SECONDS)


class Sender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpSender:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port,
                          timeout=self.s.smtp_timeout_seconds) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_user and self.s.smtp_password:
                smtp.login(self.s.smtp_user, self.s.smtp_password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)


@dataclass
class BatchResult:
    enviadas: int = 0
    reintentos: int = 0
    agotadas: int = 0


async def _claim_one(s: AsyncSession):  # type: ignore[no-untyped-def]
    return (await s.execute(text(
        """
        SELECT e.id, e.canal, e.destino, e.intentos, n.asunto, n.cuerpo
          FROM ops.entrega_notificacion e JOIN ops.notificacion n ON n.id = e.notificacion_id
         WHERE e.estado = 'PENDIENTE' AND e.proximo_intento_en <= clock_timestamp()
         ORDER BY e.proximo_intento_en
         LIMIT 1
           FOR UPDATE OF e SKIP LOCKED
        """))).mappings().first()


async def process_batch(sm: async_sessionmaker[AsyncSession], sender: Sender,
                        limit: int = 50) -> BatchResult:
    result = BatchResult()
    for _ in range(limit):
        exhausted: dict | None = None
        async with sm() as s, s.begin():
            row = await _claim_one(s)
            if row is None:
                break
            try:
                if row["canal"] == "CORREO":
                    if not row["destino"]:
                        raise ValueError("destinatario sin correo")
                    await sender.send(row["destino"], row["asunto"], row["cuerpo"])
                await s.execute(text(
                    "UPDATE ops.entrega_notificacion SET estado = 'ENVIADA', enviada_en = now(), "
                    "intentos = intentos + 1, ultimo_error = NULL WHERE id = :i"), {"i": row["id"]})
                result.enviadas += 1
            except Exception as exc:  # noqa: BLE001 - se reintenta; nunca se propaga
                attempts = row["intentos"] + 1
                error = type(exc).__name__[:200]
                if attempts >= MAX_ATTEMPTS:
                    await s.execute(text(
                        "UPDATE ops.entrega_notificacion SET estado = 'AGOTADA', intentos = :n, "
                        "ultimo_error = :e WHERE id = :i"),
                        {"n": attempts, "e": error, "i": row["id"]})
                    await generate(s, "NOT_DELIVERY_EXHAUSTED", str(row["id"]), {
                        "canal": row["canal"], "asunto_original": row["asunto"],
                        "intentos": attempts})
                    exhausted = {"entrega_id": str(row["id"]), "canal": row["canal"],
                                 "error": error, "intentos": attempts}
                    result.agotadas += 1
                else:
                    nxt = datetime.now(UTC) + timedelta(seconds=BACKOFF_SECONDS[attempts - 1])
                    await s.execute(text(
                        "UPDATE ops.entrega_notificacion SET intentos = :n, ultimo_error = :e, "
                        "proximo_intento_en = :p WHERE id = :i"),
                        {"n": attempts, "e": error, "p": nxt, "i": row["id"]})
                    result.reintentos += 1
                logger.warning("entrega %s fallida (%s), intento %d", row["canal"], error,
                               attempts)
        if exhausted:  # REQ-NOT-04: alerta técnica + registro del error
            await record_error(sm, categoria="NOTIFICACION", componente="notifications.delivery",
                               tipo="DELIVERY_EXHAUSTED", severidad="ALTA",
                               descripcion="Reintentos de entrega agotados",
                               diagnostico=exhausted)
    return result
