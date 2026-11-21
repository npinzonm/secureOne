"""API de integración con Talento Humano (E.8; CU-TH-01..06)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.kernel.authz import require
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.api.dependencies import audit_context, get_auth_service
from app.modules.auth.application.service import AuthService, Principal
from app.modules.th.application.intake import DuplicateFileError, receive
from app.modules.th.domain.contract import MAX_BYTES
from app.modules.users.api.admin_ops import AltaIn, RequestOut, create_alta

router = APIRouter(tags=["th"])


class RecepcionOut(BaseModel):
    ejecucion_id: uuid.UUID
    numero: int
    estado: str


@router.post("/admin/th/files", status_code=202, response_model=RecepcionOut)
async def upload_file(
    request: Request,
    tipo: Literal["ACTIVA", "RETIRADOS"] = Form(...),  # noqa: B008
    archivo: UploadFile = File(...),  # noqa: B008
    reproceso_de: uuid.UUID | None = Form(None),  # noqa: B008
    motivo: str | None = Form(None, max_length=1000),  # noqa: B008
    p: Principal = Depends(require("ADM.TH.CREACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> RecepcionOut:
    """CU-TH-01: carga manual (DD-05). Se procesa en el worker; el original se elimina al final."""
    content = await archivo.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise BusinessRuleError("El archivo supera 10 MB.")
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        r = await receive(uow, auth.settings.th_dir, tipo, archivo.filename or "archivo.xlsx",
                          content, p.user_id, reproceso_de, motivo)
        try:
            await uow.commit()
        except Exception:
            if not isinstance(r, DuplicateFileError):
                r.path.unlink(missing_ok=True)
            raise
    if isinstance(r, DuplicateFileError):
        raise r
    return RecepcionOut(ejecucion_id=r.id, numero=r.numero, estado=r.estado)


class EjecucionOut(BaseModel):
    id: uuid.UUID
    numero: int
    tipo: str
    nombre_archivo: str
    tamano: int
    recibido_en: datetime
    cargado_por: str | None
    estado: str
    intentos: int
    estadisticas: Any
    error: str | None
    reproceso_de: int | None
    motivo_reproceso: str | None
    finalizada_en: datetime | None
    archivo_eliminado_en: datetime | None


_EX_SELECT = """
    SELECT e.id, e.numero, e.tipo, e.nombre_archivo, e.tamano, e.recibido_en,
           u.usuario_red AS cargado_por, e.estado, e.intentos, e.estadisticas, e.error,
           o.numero AS reproceso_de, e.motivo_reproceso, e.finalizada_en, e.archivo_eliminado_en
      FROM app.ejecucion_th e
      LEFT JOIN app.usuario u ON u.id = e.cargado_por
      LEFT JOIN app.ejecucion_th o ON o.id = e.ejecucion_origen_id
"""


@router.get("/admin/th/executions", response_model=list[EjecucionOut])
async def list_executions(
    tipo: Literal["ACTIVA", "RETIRADOS"] | None = None,
    estado: str | None = Query(None, max_length=12),
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(require("ADM.TH.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[EjecucionOut]:
    async with auth.sm() as s:
        rows = (await s.execute(text(
            f"{_EX_SELECT} WHERE (CAST(:t AS text) IS NULL OR e.tipo = :t) "  # noqa: S608
            "AND (CAST(:e AS text) IS NULL OR e.estado = :e) ORDER BY e.numero DESC LIMIT :l"),
            {"t": tipo, "e": estado, "l": limit})).mappings().all()
    return [EjecucionOut(**r) for r in rows]


@router.get("/admin/th/executions/{execution_id}", response_model=EjecucionOut)
async def get_execution(
    execution_id: uuid.UUID,
    _: Principal = Depends(require("ADM.TH.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> EjecucionOut:
    async with auth.sm() as s:
        row = (await s.execute(text(f"{_EX_SELECT} WHERE e.id = :i"),  # noqa: S608
                               {"i": execution_id})).mappings().first()
    if row is None:
        raise NotFoundError()
    return EjecucionOut(**row)


class FilaOut(BaseModel):
    fila: int
    identificacion: str | None
    resultado: str
    accion: str | None
    detalle: Any


@router.get("/admin/th/executions/{execution_id}/rows", response_model=list[FilaOut])
async def execution_rows(
    execution_id: uuid.UUID,
    resultado: Literal["OK", "ERROR", "OMITIDA"] | None = None,
    limit: int = Query(500, ge=1, le=5000),
    _: Principal = Depends(require("ADM.TH.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[FilaOut]:
    async with auth.sm() as s:
        rows = (await s.execute(text(
            "SELECT fila, identificacion, resultado, accion, detalle FROM app.resultado_fila_th "
            "WHERE ejecucion_id = :e AND (CAST(:r AS text) IS NULL OR resultado = :r) "
            "ORDER BY fila LIMIT :l"), {"e": execution_id, "r": resultado, "l": limit}
        )).mappings().all()
    return [FilaOut(**r) for r in rows]


class VersionOut(BaseModel):
    version: int
    vigente: bool
    contenido: Any
    ejecucion: int
    solicitud: int | None
    creada_en: datetime


class PropuestaOut(BaseModel):
    id: uuid.UUID
    tipo: str
    identificacion: str
    estado: str
    motivo_cierre: str | None
    actualizada_en: datetime
    versiones: list[VersionOut]


async def _proposals(auth: AuthService, where: str, params: dict) -> list[PropuestaOut]:
    async with auth.sm() as s:
        props = (await s.execute(text(
            "SELECT id, tipo, identificacion, estado, motivo_cierre, actualizada_en "  # noqa: S608
            f"FROM app.propuesta_th {where} ORDER BY actualizada_en DESC LIMIT 200"),
            params)).mappings().all()
        vers = (await s.execute(text(
            "SELECT v.propuesta_id, v.version, v.vigente, v.contenido, e.numero AS ejecucion, "
            "so.numero AS solicitud, v.creada_en FROM app.propuesta_th_version v "
            "JOIN app.ejecucion_th e ON e.id = v.ejecucion_id "
            "LEFT JOIN app.solicitud so ON so.id = v.solicitud_id "
            "WHERE v.propuesta_id = ANY(:ids) ORDER BY v.version DESC"),
            {"ids": [p["id"] for p in props]})).mappings().all()
    by: dict[uuid.UUID, list[VersionOut]] = {}
    for v in vers:
        by.setdefault(v["propuesta_id"], []).append(
            VersionOut(**{k: v[k] for k in VersionOut.model_fields}))
    return [PropuestaOut(**p, versiones=by.get(p["id"], [])) for p in props]


@router.get("/admin/th/proposals", response_model=list[PropuestaOut])
async def list_proposals(
    estado: Literal["ABIERTA", "CERRADA"] | None = "ABIERTA",
    tipo: Literal["NUEVO_FUNCIONARIO", "CAMBIO_ORG"] | None = None,
    _: Principal = Depends(require("ADM.TH.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[PropuestaOut]:
    return await _proposals(auth, "WHERE (CAST(:e AS text) IS NULL OR estado = :e) "
                                  "AND (CAST(:t AS text) IS NULL OR tipo = :t)",
                            {"e": estado, "t": tipo})


@router.get("/admin/th/proposals/{proposal_id}", response_model=PropuestaOut)
async def get_proposal(
    proposal_id: uuid.UUID,
    _: Principal = Depends(require("ADM.TH.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> PropuestaOut:
    found = await _proposals(auth, "WHERE id = :i", {"i": proposal_id})
    if not found:
        raise NotFoundError()
    return found[0]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tipo_alta: Literal["NORMAL", "EXCEPCIONAL"]
    perfil: str = Field(max_length=40)
    modulos: list[str] = Field(default_factory=list, max_length=50)
    usuario_red: str | None = Field(None, max_length=16)
    correo: str | None = Field(None, max_length=150)
    motivo: str | None = Field(None, max_length=1000)


@router.post("/admin/th/proposals/{proposal_id}/decide", status_code=202,
             response_model=RequestOut)
async def decide_new_employee(
    proposal_id: uuid.UUID, body: DecisionIn, request: Request,
    p: Principal = Depends(require("ADM.USUARIO.CREACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> RequestOut:
    """CU-TH-04 / REQ-TH-11: el administrador decide alta NORMAL o EXCEPCIONAL; se crea la
    solicitud de alta con los datos de la versión vigente de la propuesta."""
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        s = uow.session
        prop = (await s.execute(text(
            "SELECT p.id, p.tipo, p.estado, p.identificacion, v.contenido FROM app.propuesta_th p "
            "JOIN app.propuesta_th_version v ON v.propuesta_id = p.id AND v.vigente "
            "WHERE p.id = :i FOR UPDATE OF p"), {"i": proposal_id})).mappings().first()
        if prop is None:
            raise NotFoundError()
        if prop["tipo"] != "NUEVO_FUNCIONARIO" or prop["estado"] != "ABIERTA":
            raise ConflictError("La propuesta no es un nuevo funcionario abierto.")
        c = prop["contenido"]
        red = body.usuario_red or c.get("usuario_red")
        correo = body.correo or c.get("correo")
        if not red or not correo:
            raise BusinessRuleError("Indique usuario de red y correo (no vienen en la planta).")
        alta = AltaIn(usuario_red=red, identificacion=prop["identificacion"],
                      nombre=c["nombres"], primer_apellido=c["primer_apellido"],
                      segundo_apellido=c.get("segundo_apellido"), correo=correo,
                      perfil=body.perfil, gerencia_id=c["gerencia_id"], area_id=c["area_id"],
                      cargo_id=c["cargo_id"], tipo_alta=body.tipo_alta, modulos=body.modulos,
                      motivo=body.motivo)
        created, uid = await create_alta(uow, p, alta)
        await s.execute(text(
            "UPDATE app.propuesta_th SET estado = 'CERRADA', motivo_cierre = :m, usuario_id = :u, "
            "actualizada_en = now() WHERE id = :i"),
            {"m": f"ALTA_SOLICITADA #{created.numero} ({body.tipo_alta})", "u": uid,
             "i": proposal_id})
        await uow.commit()
    return RequestOut(solicitud_id=created.id, numero=created.numero, tipo=created.tipo,
                      estado=created.estado, usuario_id=uid)


class AlertaOut(BaseModel):
    id: uuid.UUID
    tipo: str
    usuario_red: str | None
    abierta_en: datetime
    cerrada_en: datetime | None
    motivo_cierre: str | None
    ejecucion: int | None


@router.get("/admin/th/alerts", response_model=list[AlertaOut])
async def list_alerts(
    abiertas: bool = True,
    _: Principal = Depends(require("ADM.TH.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[AlertaOut]:
    async with auth.sm() as s:
        rows = (await s.execute(text(
            "SELECT a.id, a.tipo, u.usuario_red, a.abierta_en, a.cerrada_en, a.motivo_cierre, "
            "e.numero AS ejecucion FROM app.alerta_th a LEFT JOIN app.usuario u "
            "ON u.id = a.usuario_id LEFT JOIN app.ejecucion_th e ON e.id = a.ejecucion_id "
            "WHERE (NOT :ab OR a.cerrada_en IS NULL) ORDER BY a.abierta_en DESC LIMIT 500"),
            {"ab": abiertas})).mappings().all()
    return [AlertaOut(**r) for r in rows]
