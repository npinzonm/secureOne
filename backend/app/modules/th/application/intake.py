"""Recepción de archivos TH (CU-TH-01/06; DD-05) y alerta de archivo diario no recibido."""

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import uuid7
from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool
from app.kernel.unit_of_work import UnitOfWork
from app.modules.notifications.application.outbox import notify
from app.modules.th.domain.contract import StructuralError, Tipo, check_container

CAT = "TALENTO_HUMANO"


@dataclass(frozen=True)
class Received:
    id: uuid.UUID
    numero: int
    path: Path
    estado: str = "PENDIENTE"


class DuplicateFileError(ConflictError):
    code = "TH_DUPLICATE"
    message = "Este archivo ya fue procesado. Para reprocesarlo indique la ejecución y un motivo."


async def receive(uow: UnitOfWork, th_dir: str, tipo: Tipo, filename: str, content: bytes,
                  uploaded_by: uuid.UUID, reproceso_de: uuid.UUID | None,
                  motivo: str | None) -> Received | DuplicateFileError:
    """Registra la ejecución y deja el archivo en el volumen temporal (0600).
    Devuelve DuplicateFileError (no la lanza) para que el llamador confirme la auditoría y la
    notificación del duplicado antes de responder 409."""
    if not filename.lower().endswith(".xlsx"):
        raise BusinessRuleError("Solo se aceptan archivos .xlsx.")
    try:
        check_container(content)  # validación temprana; la estructural completa la hace el worker
    except StructuralError as exc:
        raise BusinessRuleError(f"Archivo inválido: {exc}.") from exc
    s = uow.session
    sha = hashlib.sha256(content).digest()
    if reproceso_de is not None:
        if not motivo or len(motivo.strip()) < 10:
            raise BusinessRuleError("El reproceso exige un motivo (mín. 10 caracteres).")
        orig = (await s.execute(text("SELECT tipo, estado FROM app.ejecucion_th WHERE id = :i"),
                                {"i": reproceso_de})).first()
        if orig is None:
            raise NotFoundError("La ejecución a reprocesar no existe.")
        if orig[0] != tipo or orig[1] == "PENDIENTE":
            raise BusinessRuleError("Solo se reprocesa una ejecución finalizada del mismo tipo.")
    else:
        dup = (await s.execute(text(
            "SELECT numero FROM app.ejecucion_th WHERE tipo = :t AND archivo_sha256 = :h "
            "AND estado IN ('PENDIENTE', 'COMPLETADA', 'PARCIAL') ORDER BY numero LIMIT 1"),
            {"t": tipo, "h": sha})).scalar()
        if dup is not None:  # REQ-TH-09: no se reprocesa automáticamente
            uow.audit(AuditEntry(categoria=CAT, accion="TH_DUPLICATE_REJECTED", modulo="ADM",
                                 resultado="DENEGADO", entidad="ejecucion_th",
                                 detalle={"tipo": tipo, "ejecucion_previa": dup,
                                          "sha256": sha.hex()}))
            # origen = SHA-256 (64 hex); cada intento duplicado se notifica (dedupe propio).
            await notify(uow, "TH_DUPLICATE", sha.hex(), {"tipo": tipo, "numero": dup},
                         dedupe=f"TH_DUPLICATE:{sha.hex()}:{uuid7()}")
            return DuplicateFileError(details={"ejecucion_previa": dup})

    eid = uuid7()
    path = Path(th_dir) / f"{eid}.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(content)
    numero = (await s.execute(text(
        "INSERT INTO app.ejecucion_th (id, tipo, archivo_sha256, nombre_archivo, tamano, "
        "ruta_temporal, cargado_por, ejecucion_origen_id, motivo_reproceso) VALUES "
        "(:id, :t, :h, :n, :sz, :p, :u, :o, :m) RETURNING numero"),
        {"id": eid, "t": tipo, "h": sha, "n": Path(filename).name[:200], "sz": len(content),
         "p": str(path), "u": uploaded_by, "o": reproceso_de,
         "m": motivo if reproceso_de else None})).scalar_one()
    uow.audit(AuditEntry(categoria=CAT, accion="TH_FILE_RECEIVED", modulo="ADM",
                         entidad="ejecucion_th", entidad_id=str(eid),
                         motivo=motivo if reproceso_de else None,
                         detalle={"numero": numero, "tipo": tipo, "tamano": len(content),
                                  "sha256": sha.hex(),
                                  "reproceso_de": str(reproceso_de) if reproceso_de else None}))
    return Received(eid, numero, path)


async def _param(s: AsyncSession, clave: str) -> str | None:
    return (await s.execute(text("SELECT valor FROM ops.parametro WHERE clave = :c"),
                            {"c": clave})).scalar()


async def check_missing_daily_file(sm: async_sessionmaker[AsyncSession], spool: IncidentSpool,
                                   now: datetime | None = None) -> bool:
    """REQ-TH-06 / D-TH-003: alerta si no llegó la planta activa del día tras el umbral.
    Una sola alerta por periodo continuo de ausencia (índice único de alerta abierta)."""
    async with UnitOfWork(sm, AuditContext(actor_tipo="SISTEMA"), spool) as uow:
        s = uow.session
        hora = await _param(s, "th.hora_habitual")
        if not hora:
            return False  # sin hora habitual definida no hay referencia para alertar
        umbral = int(await _param(s, "th.umbral_alerta_horas") or 4)
        tz = ZoneInfo(await _param(s, "th.zona_horaria") or "America/Bogota")
        local_now = (now or datetime.now(tz)).astimezone(tz)
        hh, mm = (int(x) for x in hora.split(":"))
        due = datetime.combine(local_now.date(), time(hh, mm), tz) + timedelta(hours=umbral)
        if local_now < due:
            return False
        start = datetime.combine(local_now.date(), time(0, 0), tz)
        received = (await s.execute(text(
            "SELECT 1 FROM app.ejecucion_th WHERE tipo = 'ACTIVA' AND recibido_en >= :d "
            "AND estado <> 'RECHAZADA' LIMIT 1"), {"d": start})).first()
        if received:
            return False
        fecha = local_now.date().isoformat()
        new = (await s.execute(text(
            "INSERT INTO app.alerta_th (id, tipo, referencia) VALUES (:id, 'ARCHIVO_NO_RECIBIDO', "
            "'DIARIO') ON CONFLICT (tipo, referencia) WHERE cerrada_en IS NULL DO NOTHING "
            "RETURNING id"), {"id": uuid7()})).scalar()
        if new is None:
            return False
        uow.audit(AuditEntry(categoria=CAT, accion="TH_ALERT_RAISED", modulo="ADM",
                             entidad="alerta_th", entidad_id=str(new),
                             detalle={"tipo": "ARCHIVO_NO_RECIBIDO", "fecha": fecha}))
        await notify(uow, "TH_FILE_MISSING", f"{fecha}",
                     {"fecha": fecha, "umbral": umbral, "hora": hora})
        await uow.commit()
        return True

