"""Auditoría centralizada (REQ-AUD-01..08).

- `AuditEntry`: evento a registrar. Los valores antes/después y el detalle se sanean
  (claves sensibles enmascaradas) antes de persistir (REQ-AUD-03).
- `AuditContext`: actor, IP y user-agent de la petición.
- `insert_audit`: INSERT en `audit.evento` dentro de la transacción recibida.
- `IncidentSpool`: archivo local de contingencia para operaciones bloqueadas por caída de
  auditoría; se vuelca a `ops.registro_error` al recuperarse el servicio (P §9.1).
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import uuid7
from app.core.logging import correlation_id_var, redact
from app.kernel.models import audit_evento, ops_registro_error

logger = logging.getLogger(__name__)

Resultado = Literal["EXITO", "FALLO", "DENEGADO"]
ActorTipo = Literal["USUARIO", "SISTEMA", "TH"]


@dataclass(frozen=True)
class AuditContext:
    actor_id: UUID | None = None
    actor_usuario_red: str | None = None
    actor_tipo: ActorTipo = "USUARIO"
    ip_origen: str | None = None
    user_agent: str | None = None

    @classmethod
    def system(cls) -> "AuditContext":
        return cls(actor_tipo="SISTEMA")


@dataclass(frozen=True)
class AuditEntry:
    categoria: str
    accion: str
    resultado: Resultado = "EXITO"
    modulo: str | None = None
    entidad: str | None = None
    entidad_id: str | None = None
    valor_anterior: dict[str, Any] | None = None
    valor_nuevo: dict[str, Any] | None = None
    motivo: str | None = None
    detalle: dict[str, Any] | None = None
    solicitud_id: UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _sanitize(value: dict[str, Any] | None) -> Any:
    return None if value is None else json.loads(json.dumps(redact(value), default=str))


def build_audit_row(entry: AuditEntry, ctx: AuditContext) -> dict[str, Any]:
    return {
        "id": uuid7(),
        "actor_id": ctx.actor_id,
        "actor_usuario_red": ctx.actor_usuario_red,
        "actor_tipo": ctx.actor_tipo,
        "categoria": entry.categoria,
        "modulo": entry.modulo,
        "accion": entry.accion,
        "entidad": entry.entidad,
        "entidad_id": entry.entidad_id,
        "valor_anterior": _sanitize(entry.valor_anterior),
        "valor_nuevo": _sanitize(entry.valor_nuevo),
        "resultado": entry.resultado,
        "motivo": entry.motivo,
        "ip_origen": ctx.ip_origen,
        "user_agent": (ctx.user_agent or None) and ctx.user_agent[:512],
        "detalle": _sanitize(entry.detalle),
        "correlation_id": correlation_id_var.get(),
        "solicitud_id": entry.solicitud_id,
    }


async def insert_audit(session: AsyncSession, entry: AuditEntry, ctx: AuditContext) -> None:
    await session.execute(insert(audit_evento).values(**build_audit_row(entry, ctx)))


class IncidentSpool:
    """Spool JSONL local. Solo metadatos de la operación bloqueada: nunca valores de negocio."""

    FILE = "audit-incidents.jsonl"

    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)

    def record(self, entry: AuditEntry, ctx: AuditContext, error_type: str) -> bool:
        line = json.dumps(
            {
                "ts": datetime.now(UTC).isoformat(),
                "correlation_id": correlation_id_var.get(),
                "categoria": entry.categoria,
                "modulo": entry.modulo,
                "accion": entry.accion,
                "entidad": entry.entidad,
                "entidad_id": entry.entidad_id,
                "actor_id": str(ctx.actor_id) if ctx.actor_id else None,
                "actor_tipo": ctx.actor_tipo,
                "error_type": error_type,
            },
            ensure_ascii=False,
        )
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.dir / self.FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return True
        except OSError as exc:
            logger.critical("no se pudo escribir el spool de incidentes (%s)", type(exc).__name__)
            return False

    def _claim(self) -> list[Path]:
        """Toma de forma atómica el archivo pendiente (rename) más los que quedaron a medias."""
        claimed = sorted(self.dir.glob("processing-*.jsonl"))
        src = self.dir / self.FILE
        if src.exists():
            dst = self.dir / f"processing-{time.time_ns()}.jsonl"
            os.replace(src, dst)
            claimed.append(dst)
        return claimed

    async def flush(self, sessionmaker: async_sessionmaker[AsyncSession]) -> int:
        """Vuelca incidentes a ops.registro_error + un evento OPS_AUDIT_OUTAGE_RECORDED.

        Devuelve el número de incidentes registrados. Si falla, los archivos quedan para
        el próximo intento (no se pierde nada).
        """
        if not self.dir.exists():
            return 0
        files = self._claim()
        if not files:
            return 0
        incidents: list[dict[str, Any]] = []
        for f in files:
            for raw in f.read_text(encoding="utf-8").splitlines():
                if raw.strip():
                    incidents.append(json.loads(raw))
        if incidents:
            async with sessionmaker() as session, session.begin():
                for inc in incidents:
                    await session.execute(
                        insert(ops_registro_error).values(
                            id=uuid7(),
                            categoria="AUDITORIA",
                            modulo=inc.get("modulo"),
                            componente="kernel.audit",
                            tipo="AUDIT_UNAVAILABLE",
                            severidad="CRITICA",
                            descripcion=(
                                "Operación bloqueada por indisponibilidad de auditoría: "
                                f"{inc.get('accion')}"
                            ),
                            diagnostico=redact(inc),
                            correlation_id=inc.get("correlation_id"),
                        )
                    )
                await insert_audit(
                    session,
                    AuditEntry(
                        categoria="OPERACION",
                        accion="OPS_AUDIT_OUTAGE_RECORDED",
                        detalle={
                            "incidentes": len(incidents),
                            "desde": incidents[0].get("ts"),
                            "hasta": incidents[-1].get("ts"),
                        },
                    ),
                    AuditContext.system(),
                )
        for f in files:
            f.unlink(missing_ok=True)
        return len(incidents)
