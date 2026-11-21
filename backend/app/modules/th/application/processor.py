"""Procesamiento de plantas de Talento Humano (worker; REQ-TH-01..13, DD-03/04/05).

Una ejecución se procesa en UNA transacción (UnitOfWork, actor TH): o se registra todo
(resultados, catálogos, propuestas, solicitudes, alertas, auditoría, notificaciones) o nada.
Eso hace idempotentes los reintentos técnicos (1, 5, 15 min; REQ-TH-10).
El archivo original se elimina al llegar a un estado final; solo se conserva su SHA-256.
"""

import dataclasses
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import uuid7
from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool
from app.kernel.error_registry import record_error
from app.kernel.unit_of_work import UnitOfWork
from app.modules.approvals.application.requests import Item, create_request, pending_for
from app.modules.notifications.application.outbox import notify
from app.modules.th.domain.contract import ParsedFile, Row, StructuralError, parse

logger = logging.getLogger(__name__)
RETRY_SECONDS = (60, 300, 900)  # REQ-TH-10
TH_CTX = AuditContext(actor_tipo="TH", actor_usuario_red="Talento Humano")
CAT = "TALENTO_HUMANO"


@dataclass
class Stats:
    filas: int = 0
    ok: int = 0
    errores: int = 0
    omitidas: int = 0
    solicitudes: int = 0
    propuestas: int = 0
    ausentes_nuevos: int = 0
    catalogos: dict[str, int] = field(default_factory=dict)
    columnas_desconocidas: list[str] = field(default_factory=list)


@dataclass
class _Result:
    fila: int
    identificacion: str | None
    resultado: str
    accion: str | None = None
    detalle: dict[str, Any] | None = None


def _delete_file(path: str | None) -> None:
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            logger.error("no se pudo eliminar el archivo TH (%s)", type(exc).__name__)


# =========================================================================== orquestación

async def process_next(sm: async_sessionmaker[AsyncSession], spool: IncidentSpool) -> bool:
    """Procesa UNA ejecución pendiente (retirados primero). Devuelve True si procesó alguna."""
    ex: dict[str, Any] | None = None
    try:
        async with UnitOfWork(sm, TH_CTX, spool) as uow:
            row = (await uow.session.execute(text(
                "SELECT * FROM app.ejecucion_th WHERE estado = 'PENDIENTE' "
                "AND proximo_intento_en <= now() ORDER BY (tipo = 'ACTIVA'), recibido_en "
                "LIMIT 1 FOR UPDATE SKIP LOCKED"))).mappings().first()
            if row is None:
                return False
            ex = dict(row)
            try:
                parsed = parse(Path(ex["ruta_temporal"]).read_bytes(), ex["tipo"])
            except StructuralError as se:
                await _finish(uow, ex, "RECHAZADA", None, str(se))
                await uow.commit()
                _delete_file(ex["ruta_temporal"])
                return True
            stats = Stats(filas=len(parsed.rows), columnas_desconocidas=parsed.unknown_columns)
            results = (await _apply_retirados(uow, ex, parsed, stats) if ex["tipo"] == "RETIRADOS"
                       else await _apply_activa(uow, ex, parsed, stats))
            await _store_results(uow.session, ex["id"], results)
            estado = "PARCIAL" if stats.errores else "COMPLETADA"
            await _finish(uow, ex, estado, stats, None)
            await uow.commit()
        _delete_file(ex["ruta_temporal"])
        return True
    except Exception as exc:  # noqa: BLE001 - falla técnica: reintento programado
        if ex is None:
            raise
        logger.error("falla técnica procesando TH #%s (%s)", ex["numero"], type(exc).__name__)
        await _register_failure(sm, spool, ex["id"], exc)
        return True


async def _finish(uow: UnitOfWork, ex: dict, estado: str, stats: Stats | None,
                  error: str | None) -> None:
    st = dataclasses.asdict(stats) if stats else None
    await uow.session.execute(text(
        "UPDATE app.ejecucion_th SET estado = :e, estadisticas = CAST(:s AS jsonb), error = :err, "
        "finalizada_en = now(), ruta_temporal = NULL, archivo_eliminado_en = now() WHERE id = :i"),
        {"e": estado, "s": json.dumps(st) if st else None, "err": error, "i": ex["id"]})
    ctx = {"numero": ex["numero"], "tipo": ex["tipo"], "estado": estado}
    if estado == "RECHAZADA":
        uow.audit(AuditEntry(categoria=CAT, accion="TH_EXECUTION_REJECTED", modulo="ADM",
                             resultado="FALLO", entidad="ejecucion_th", entidad_id=str(ex["id"]),
                             detalle={**ctx, "error": error}))
        await notify(uow, "TH_EXECUTION_REJECTED", str(ex["id"]), {**ctx, "error": error})
    else:
        uow.audit(AuditEntry(categoria=CAT, accion="TH_EXECUTION_COMPLETED", modulo="ADM",
                             entidad="ejecucion_th", entidad_id=str(ex["id"]),
                             detalle={**ctx, **(st or {})}))
        await notify(uow, "TH_EXECUTION_DONE", str(ex["id"]), {**ctx, **(st or {})})
    uow.audit(AuditEntry(categoria=CAT, accion="TH_FILE_PURGED", modulo="ADM",
                         entidad="ejecucion_th", entidad_id=str(ex["id"]),
                         detalle={"sha256": ex["archivo_sha256"].hex()}))


async def _register_failure(sm: async_sessionmaker[AsyncSession], spool: IncidentSpool,
                            ex_id: uuid.UUID, exc: Exception) -> None:
    path = None
    exhausted = False
    try:
        async with UnitOfWork(sm, TH_CTX, spool) as uow:
            ex = (await uow.session.execute(text(
                "SELECT * FROM app.ejecucion_th WHERE id = :i FOR UPDATE"),
                {"i": ex_id})).mappings().one()
            if ex["estado"] != "PENDIENTE":
                return
            attempts = ex["intentos"] + 1
            ctx = {"numero": ex["numero"], "tipo": ex["tipo"], "intentos": attempts}
            if attempts >= len(RETRY_SECONDS):
                path, exhausted = ex["ruta_temporal"], True
                await uow.session.execute(text(
                    "UPDATE app.ejecucion_th SET estado = 'FALLIDA', intentos = :n, error = :e, "
                    "finalizada_en = now(), ruta_temporal = NULL, archivo_eliminado_en = now() "
                    "WHERE id = :i"), {"n": attempts, "e": type(exc).__name__, "i": ex_id})
                uow.audit(AuditEntry(categoria=CAT, accion="TH_RETRY_EXHAUSTED", modulo="ADM",
                                     resultado="FALLO", entidad="ejecucion_th",
                                     entidad_id=str(ex_id), detalle=ctx))
                await notify(uow, "TH_EXECUTION_FAILED", str(ex_id), ctx)
            else:
                nxt = datetime.now(UTC) + timedelta(seconds=RETRY_SECONDS[attempts - 1])
                await uow.session.execute(text(
                    "UPDATE app.ejecucion_th SET intentos = :n, error = :e, "
                    "proximo_intento_en = :p WHERE id = :i"),
                    {"n": attempts, "e": type(exc).__name__, "p": nxt, "i": ex_id})
                uow.audit(AuditEntry(categoria=CAT, accion="TH_RETRY_SCHEDULED", modulo="ADM",
                                     resultado="FALLO", entidad="ejecucion_th",
                                     entidad_id=str(ex_id), detalle=ctx))
            await uow.commit()
    except Exception as inner:  # noqa: BLE001 - se reintentará en el próximo ciclo
        logger.error("no se pudo registrar la falla TH (%s)", type(inner).__name__)
        return
    _delete_file(path)
    if exhausted:
        await record_error(sm, categoria="INTEGRACION", componente="th.processor",
                           tipo="TH_RETRY_EXHAUSTED", severidad="ALTA",
                           descripcion="Reintentos técnicos agotados al procesar planta TH",
                           diagnostico={"ejecucion_id": str(ex_id), "error": type(exc).__name__})


async def _store_results(s: AsyncSession, ex_id: uuid.UUID, results: list[_Result]) -> None:
    if results:
        await s.execute(text(
            "INSERT INTO app.resultado_fila_th (ejecucion_id, fila, identificacion, resultado, "
            "accion, detalle) VALUES (:e, :f, :i, :r, :a, CAST(:d AS jsonb))"),
            [{"e": ex_id, "f": r.fila, "i": r.identificacion, "r": r.resultado, "a": r.accion,
              "d": json.dumps(r.detalle) if r.detalle else None} for r in results])


def _error(row: Row, stats: Stats) -> _Result:
    stats.errores += 1
    return _Result(row.fila, row.identificacion, "ERROR", None, {"errores": row.errors})


def _omit(row: Row, stats: Stats, motivo: str) -> _Result:
    stats.omitidas += 1
    return _Result(row.fila, row.identificacion, "OMITIDA", motivo)


def _ok(row: Row, stats: Stats, accion: str, detalle: dict | None = None) -> _Result:
    stats.ok += 1
    return _Result(row.fila, row.identificacion, "OK", accion, detalle)


async def _user_by_ident(s: AsyncSession, ident: str) -> dict[str, Any] | None:
    r = (await s.execute(text(
        "SELECT id, usuario_red, estado, gerencia_id, area_id, cargo_id FROM app.usuario "
        "WHERE upper(identificacion) = upper(:i)"), {"i": ident})).mappings().first()
    return dict(r) if r else None


# =========================================================================== retirados

async def _apply_retirados(uow: UnitOfWork, ex: dict, parsed: ParsedFile,
                           stats: Stats) -> list[_Result]:
    out: list[_Result] = []
    for row in parsed.rows:
        if not row.ok:
            out.append(_error(row, stats))
            continue
        u = await _user_by_ident(uow.session, row.identificacion or "")
        if u is None:
            out.append(_omit(row, stats, "USUARIO_INEXISTENTE"))
        elif u["estado"] != "ACTIVO":
            out.append(_omit(row, stats, "USUARIO_NO_ACTIVO"))
        elif row.data.get("USUARIO_RED") and row.data["USUARIO_RED"] != u["usuario_red"]:
            out.append(_omit(row, stats, "COINCIDENCIA_AMBIGUA"))  # DD-04: no es inequívoca
        elif await pending_for(uow.session, "usuario", u["id"]) is not None:
            out.append(_omit(row, stats, "SOLICITUD_PENDIENTE"))
        else:  # REQ-TH-03: solicitud, nunca inhabilitación automática
            created = await create_request(
                uow, tipo="INHABILITACION_USUARIO", entidad="usuario", entidad_id=u["id"],
                solicitante_id=None, origen="TH",
                motivo=(f"Retiro reportado por Talento Humano (fecha {row.data['FECHA_RETIRO']}, "
                        f"ejecución #{ex['numero']})."),
                items=[Item("estado", "ACTIVO", "INACTIVO")])
            stats.solicitudes += 1
            out.append(_ok(row, stats, "SOLICITUD_INHABILITACION", {"numero": created.numero}))
    return out


# =========================================================================== planta activa

async def _sync_catalogs(s: AsyncSession, rows: list[Row], stats: Stats) -> dict[str, dict]:
    """REQ-TH-13: catálogos solo desde TH, por código; ausentes → INACTIVO."""
    # Consistencia área → gerencia dentro del archivo y respecto de la BD.
    area_ger: dict[str, set[str]] = {}
    for r in rows:
        area_ger.setdefault(r.data["CODIGO_AREA"], set()).add(r.data["CODIGO_GERENCIA"])
    existing = dict((await s.execute(text(
        "SELECT a.codigo, g.codigo FROM app.area a JOIN app.gerencia g ON g.id = a.gerencia_id"
    ))).all())
    for r in rows:
        a = r.data["CODIGO_AREA"]
        if len(area_ger[a]) > 1:
            r.errors.append("AREA_EN_VARIAS_GERENCIAS")
        elif a in existing and existing[a] != r.data["CODIGO_GERENCIA"]:
            r.errors.append("AREA_CAMBIA_DE_GERENCIA")
    valid = [r for r in rows if r.ok]
    maps: dict[str, dict] = {"gerencia": {}, "area": {}, "cargo": {}}
    if not valid:
        return maps
    for r in valid:
        gid = (await s.execute(text(
            "INSERT INTO app.gerencia (codigo, nombre) VALUES (:c, :n) ON CONFLICT (codigo) DO "
            "UPDATE SET nombre = EXCLUDED.nombre, estado = 'ACTIVO', inhabilitado_en = NULL, "
            "modificado_en = CASE WHEN app.gerencia.nombre <> EXCLUDED.nombre "
            "OR app.gerencia.estado <> 'ACTIVO' THEN now() ELSE app.gerencia.modificado_en END "
            "RETURNING id"), {"c": r.data["CODIGO_GERENCIA"], "n": r.data["GERENCIA"]})).scalar()
        maps["gerencia"][r.data["CODIGO_GERENCIA"]] = gid
        maps["area"][r.data["CODIGO_AREA"]] = (await s.execute(text(
            "INSERT INTO app.area (codigo, nombre, gerencia_id) VALUES (:c, :n, :g) "
            "ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre, estado = 'ACTIVO', "
            "inhabilitado_en = NULL RETURNING id"),
            {"c": r.data["CODIGO_AREA"], "n": r.data["AREA"], "g": gid})).scalar()
        maps["cargo"][r.data["CODIGO_CARGO"]] = (await s.execute(text(
            "INSERT INTO app.cargo (codigo_cargo, nombre) VALUES (:c, :n) ON CONFLICT "
            "(codigo_cargo) DO UPDATE SET nombre = EXCLUDED.nombre, estado = 'ACTIVO', "
            "inhabilitado_en = NULL RETURNING id"),
            {"c": r.data["CODIGO_CARGO"], "n": r.data["CARGO"]})).scalar()
    for table, col, codes in (("gerencia", "codigo", list(maps["gerencia"])),
                              ("area", "codigo", list(maps["area"])),
                              ("cargo", "codigo_cargo", list(maps["cargo"]))):
        n = (await s.execute(text(
            f"UPDATE app.{table} SET estado = 'INACTIVO', inhabilitado_en = now() "  # noqa: S608
            f"WHERE estado = 'ACTIVO' AND NOT ({col} = ANY(:c)) RETURNING id"),
            {"c": codes})).all()
        stats.catalogos[f"{table}_activos"] = len(codes)
        stats.catalogos[f"{table}_inactivados"] = len(n)
    return maps


async def _version(s: AsyncSession, tipo: str, ident: str, contenido: dict, ex_id: uuid.UUID,
                   usuario_id: uuid.UUID | None) -> tuple[uuid.UUID | None, dict | None]:
    """Versiona la propuesta bajo un ID estable. Devuelve (id nueva versión, versión anterior).
    (None, None) si el contenido no cambió respecto de la versión vigente."""
    prop = (await s.execute(text(
        "SELECT id FROM app.propuesta_th WHERE tipo = :t AND upper(identificacion) = upper(:i) "
        "AND estado = 'ABIERTA' FOR UPDATE"), {"t": tipo, "i": ident})).scalar()
    prev = None
    if prop is None:
        prop = uuid7()
        await s.execute(text(
            "INSERT INTO app.propuesta_th (id, tipo, identificacion, usuario_id) "
            "VALUES (:id, :t, :i, :u)"), {"id": prop, "t": tipo, "i": ident, "u": usuario_id})
    else:
        prev = (await s.execute(text(
            "SELECT id, version, contenido, solicitud_id FROM app.propuesta_th_version "
            "WHERE propuesta_id = :p AND vigente"), {"p": prop})).mappings().first()
        if prev is not None and prev["contenido"] == contenido:
            return None, None
        await s.execute(text("UPDATE app.propuesta_th_version SET vigente = false "
                             "WHERE propuesta_id = :p AND vigente"), {"p": prop})
    vid = uuid7()
    await s.execute(text(
        "INSERT INTO app.propuesta_th_version (id, propuesta_id, version, ejecucion_id, "
        "contenido, vigente) VALUES (:id, :p, :v, :e, CAST(:c AS jsonb), true)"),
        {"id": vid, "p": prop, "v": (prev["version"] + 1) if prev else 1, "e": ex_id,
         "c": json.dumps(contenido)})
    await s.execute(text("UPDATE app.propuesta_th SET actualizada_en = now() WHERE id = :p"),
                    {"p": prop})
    return vid, dict(prev) if prev else None


async def _supersede(uow: UnitOfWork, solicitud_id: uuid.UUID | None, motivo: str) -> None:
    if solicitud_id is None:
        return
    done = (await uow.session.execute(text(
        "UPDATE app.solicitud SET estado = 'SUPERADA', resuelta_en = now(), "
        "motivo_resolucion = :m WHERE id = :i AND estado = 'PENDIENTE' RETURNING numero"),
        {"m": motivo, "i": solicitud_id})).scalar()
    if done is not None:
        uow.audit(AuditEntry(categoria="APROBACIONES", accion="APR_SUPERSEDED", modulo="ADM",
                             entidad="solicitud", entidad_id=str(solicitud_id),
                             solicitud_id=solicitud_id, motivo=motivo,
                             detalle={"numero": done}))


async def _close_proposal(uow: UnitOfWork, tipo: str, ident: str, motivo: str) -> None:
    prev = (await uow.session.execute(text(
        "UPDATE app.propuesta_th SET estado = 'CERRADA', motivo_cierre = :m, "
        "actualizada_en = now() WHERE tipo = :t AND upper(identificacion) = upper(:i) "
        "AND estado = 'ABIERTA' RETURNING id"), {"m": motivo, "t": tipo, "i": ident})).scalar()
    if prev is not None:
        sid = (await uow.session.execute(text(
            "SELECT solicitud_id FROM app.propuesta_th_version WHERE propuesta_id = :p "
            "AND vigente"), {"p": prev})).scalar()
        await _supersede(uow, sid, f"Propuesta TH cerrada: {motivo}")


async def _apply_activa(uow: UnitOfWork, ex: dict, parsed: ParsedFile,
                        stats: Stats) -> list[_Result]:
    s = uow.session
    present = {r.identificacion.upper() for r in parsed.rows if r.identificacion}
    maps = await _sync_catalogs(s, [r for r in parsed.rows if r.ok], stats)
    out: list[_Result] = []
    any_valid = False
    for row in parsed.rows:
        if not row.ok:
            out.append(_error(row, stats))
            continue
        any_valid = True
        ident = row.identificacion or ""
        u = await _user_by_ident(s, ident)
        g = maps["gerencia"][row.data["CODIGO_GERENCIA"]]
        a = maps["area"][row.data["CODIGO_AREA"]]
        c = maps["cargo"][row.data["CODIGO_CARGO"]]
        if u is None:  # REQ-TH-11: no se crea la cuenta; propuesta para decisión del admin
            contenido = {k.lower(): row.data.get(k) for k in (
                "NOMBRES", "PRIMER_APELLIDO", "SEGUNDO_APELLIDO", "CORREO", "USUARIO_RED",
                "CODIGO_GERENCIA", "CODIGO_AREA", "CODIGO_CARGO")}
            contenido |= {"gerencia_id": str(g), "area_id": str(a), "cargo_id": str(c)}
            vid, _ = await _version(s, "NUEVO_FUNCIONARIO", ident, contenido, ex["id"], None)
            if vid:
                stats.propuestas += 1
            out.append(_ok(row, stats, "PROPUESTA_NUEVO" if vid else "SIN_CAMBIOS"))
            continue
        await _close_proposal(uow, "NUEVO_FUNCIONARIO", ident, "USUARIO_EXISTE")
        if u["estado"] != "ACTIVO":
            out.append(_omit(row, stats, "USUARIO_NO_ACTIVO"))
            continue
        target = {"gerencia_id": str(g), "area_id": str(a), "cargo_id": str(c)}
        current = {k: (str(u[k]) if u[k] else None) for k in target}
        if target == current:
            await _close_proposal(uow, "CAMBIO_ORG", ident, "SIN_DIFERENCIAS")
            out.append(_ok(row, stats, "SIN_CAMBIOS"))
            continue
        pending = await pending_for(s, "usuario", u["id"])
        prop_sol = (await s.execute(text(
            "SELECT v.solicitud_id FROM app.propuesta_th p JOIN app.propuesta_th_version v "
            "ON v.propuesta_id = p.id AND v.vigente WHERE p.tipo = 'CAMBIO_ORG' "
            "AND upper(p.identificacion) = upper(:i) AND p.estado = 'ABIERTA'"),
            {"i": ident})).scalar()
        pending_is_ours = pending is not None and prop_sol is not None and (await s.execute(text(
            "SELECT numero FROM app.solicitud WHERE id = :i"), {"i": prop_sol})).scalar() == pending
        if pending is not None and not pending_is_ours:
            out.append(_omit(row, stats, "SOLICITUD_PENDIENTE"))
            continue
        vid, prev = await _version(s, "CAMBIO_ORG", ident, target, ex["id"], u["id"])
        if vid is None:
            out.append(_ok(row, stats, "SIN_CAMBIOS"))
            continue
        await _supersede(uow, prev["solicitud_id"] if prev else None,
                         "Nueva versión de la propuesta de Talento Humano")
        changed = [k for k in target if target[k] != current[k]]
        created = await create_request(
            uow, tipo="MODIFICACION_USUARIO", entidad="usuario", entidad_id=u["id"],
            solicitante_id=None, origen="TH", propuesta_version_id=vid,
            motivo=f"Cambio organizacional reportado por TH (ejecución #{ex['numero']}).",
            items=[Item(k, current[k], target[k]) for k in changed])
        await s.execute(text("UPDATE app.propuesta_th_version SET solicitud_id = :s WHERE id = :v"),
                        {"s": created.id, "v": vid})
        stats.propuestas += 1
        stats.solicitudes += 1
        out.append(_ok(row, stats, "SOLICITUD_CAMBIO_ORG", {"numero": created.numero}))

    if any_valid:
        await _absences(uow, ex, present, stats)
        await s.execute(text(
            "UPDATE app.alerta_th SET cerrada_en = now(), motivo_cierre = 'ARCHIVO_RECIBIDO' "
            "WHERE tipo = 'ARCHIVO_NO_RECIBIDO' AND cerrada_en IS NULL"))
    return out


async def _absences(uow: UnitOfWork, ex: dict, present: set[str], stats: Stats) -> None:
    """REQ-TH-05: alerta por usuario activo ausente; una por periodo continuo."""
    s = uow.session
    await s.execute(text(
        "UPDATE app.alerta_th al SET cerrada_en = now(), motivo_cierre = 'REAPARECE' "
        "FROM app.usuario u WHERE al.tipo = 'USUARIO_AUSENTE' AND al.cerrada_en IS NULL "
        "AND al.usuario_id = u.id AND upper(u.identificacion) = ANY(:p)"), {"p": list(present)})
    absent = (await s.execute(text(
        "SELECT id FROM app.usuario WHERE estado = 'ACTIVO' "
        "AND NOT (upper(identificacion) = ANY(:p))"), {"p": list(present)})).scalars().all()
    new = 0
    for uid in absent:
        got = (await s.execute(text(
            "INSERT INTO app.alerta_th (id, tipo, usuario_id, referencia, ejecucion_id) "
            "VALUES (:id, 'USUARIO_AUSENTE', :u, :r, :e) ON CONFLICT (tipo, referencia) "
            "WHERE cerrada_en IS NULL DO NOTHING RETURNING id"),
            {"id": uuid7(), "u": uid, "r": str(uid), "e": ex["id"]})).scalar()
        new += got is not None
    stats.ausentes_nuevos = new
    if new:
        uow.audit(AuditEntry(categoria=CAT, accion="TH_ALERT_RAISED", modulo="ADM",
                             entidad="ejecucion_th", entidad_id=str(ex["id"]),
                             detalle={"tipo": "USUARIO_AUSENTE", "cantidad": new}))
        await notify(uow, "TH_USERS_ABSENT", f"{ex['id']}",
                     {"numero": ex["numero"], "cantidad": new})
