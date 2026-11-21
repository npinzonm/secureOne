"""Consulta administrativa de usuarios (Fase 4; CU-USR-01, CU-USR-02, CU-AUTH-07).

- Listado con filtros aprobados (P §6.1). Sin Empresa. No se audita (D-AUD-001: búsqueda rutinaria).
- Ficha y actividad: consultas sensibles auditadas (PD-24 PROPUESTO), fail-closed.
Las operaciones que modifican usuarios llegan en la Fase 5 (PD-05).
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.core.errors import NotFoundError
from app.core.excel import MAX_EXPORT_ROWS, build_xlsx, xlsx_response
from app.kernel.audit import AuditEntry
from app.kernel.authz import require
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.api.dependencies import audit_context, get_auth_service
from app.modules.auth.application.service import AuthService, Principal

router = APIRouter(tags=["users"])

_USER_SELECT = """
    SELECT u.id, u.usuario_red, u.identificacion, u.nombre, u.primer_apellido,
           u.segundo_apellido, u.correo, u.tipo_alta, u.estado, u.ultimo_ingreso,
           pf.codigo AS perfil_codigo, pf.nombre AS perfil_nombre,
           g.id AS gerencia_id, g.nombre AS gerencia, a.id AS area_id, a.nombre AS area,
           c.id AS cargo_id, c.nombre AS cargo, c.codigo_cargo
      FROM app.usuario u
      JOIN app.perfil pf ON pf.id = u.perfil_id
      LEFT JOIN app.gerencia g ON g.id = u.gerencia_id
      LEFT JOIN app.area a ON a.id = u.area_id
      LEFT JOIN app.cargo c ON c.id = u.cargo_id
"""


class UsuarioOut(BaseModel):
    id: uuid.UUID
    usuario_red: str
    identificacion: str
    nombre: str
    primer_apellido: str
    segundo_apellido: str | None
    correo: str
    tipo_alta: str | None
    estado: str
    ultimo_ingreso: datetime | None
    perfil_codigo: str
    perfil_nombre: str
    gerencia_id: uuid.UUID | None
    gerencia: str | None
    area_id: uuid.UUID | None
    area: str | None
    cargo_id: uuid.UUID | None
    cargo: str | None
    codigo_cargo: int | None


class UsuariosPage(BaseModel):
    items: list[UsuarioOut]
    total: int
    page: int
    page_size: int


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class UserFilter(BaseModel):
    """Filtros aprobados de la consulta central (P §6.1, REQ-USER-10)."""

    model_config = ConfigDict(extra="forbid")
    nombre: str | None = Field(None, max_length=100, description="Nombre o apellidos")
    usuario_red: str | None = Field(None, max_length=16)
    identificacion: str | None = Field(None, max_length=20)
    correo: str | None = Field(None, max_length=150)
    gerencia_id: uuid.UUID | None = None
    area_id: uuid.UUID | None = None
    cargo_id: uuid.UUID | None = None
    estado: Literal["PENDIENTE_ALTA", "ACTIVO", "INACTIVO"] | None = None
    tipo_alta: Literal["NORMAL", "EXCEPCIONAL"] | None = None

    def sql(self) -> tuple[str, dict[str, Any]]:
        where = """
         WHERE (CAST(:nombre AS text) IS NULL
                OR (u.nombre || ' ' || u.primer_apellido || ' ' || coalesce(u.segundo_apellido, ''))
                   ILIKE :nombre)
           AND (CAST(:red AS text) IS NULL OR u.usuario_red ILIKE :red)
           AND (CAST(:ident AS text) IS NULL OR u.identificacion ILIKE :ident)
           AND (CAST(:correo AS text) IS NULL OR u.correo ILIKE :correo)
           AND (CAST(:g AS uuid) IS NULL OR u.gerencia_id = :g)
           AND (CAST(:a AS uuid) IS NULL OR u.area_id = :a)
           AND (CAST(:c AS uuid) IS NULL OR u.cargo_id = :c)
           AND (CAST(:estado AS text) IS NULL OR u.estado = :estado)
           AND (CAST(:tipo AS text) IS NULL OR u.tipo_alta = :tipo)
        """
        params = {
            "nombre": _like(self.nombre) if self.nombre else None,
            "red": _like(self.usuario_red.strip().lower()) if self.usuario_red else None,
            "ident": _like(self.identificacion) if self.identificacion else None,
            "correo": _like(self.correo) if self.correo else None,
            "g": self.gerencia_id, "a": self.area_id, "c": self.cargo_id,
            "estado": self.estado, "tipo": self.tipo_alta,
        }
        return where, params


@router.get("/admin/users", response_model=UsuariosPage)
async def list_users(
    f: UserFilter = Depends(),  # noqa: B008
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    _: Principal = Depends(require("ADM.USUARIO.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> UsuariosPage:
    where, params = f.sql()
    async with auth.sm() as s:
        total = (await s.execute(text(f"SELECT count(*) FROM app.usuario u {where}"),  # noqa: S608
                                 params)).scalar_one()
        rows = (await s.execute(
            text(f"{_USER_SELECT} {where} ORDER BY u.usuario_red LIMIT :lim OFFSET :off"),  # noqa: S608
            {**params, "lim": page_size, "off": (page - 1) * page_size},
        )).mappings().all()
    return UsuariosPage(items=[UsuarioOut(**r) for r in rows], total=total,
                        page=page, page_size=page_size)


EXPORT_COLUMNS = ("usuario_red", "identificacion", "nombre", "primer_apellido",
                  "segundo_apellido", "correo", "perfil_codigo", "gerencia", "area", "cargo",
                  "codigo_cargo", "tipo_alta", "estado", "ultimo_ingreso")


@router.post("/admin/users/export")
async def export_users(
    f: UserFilter, request: Request,
    p: Principal = Depends(require("ADM.USUARIO.EXPORTACION")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> Response:
    """CU-USR-07 / REQ-USER-11: exportación Excel de lo filtrado, auditada; solo campos
    aprobados (REQ-USER-03)."""
    where, params = f.sql()
    async with auth.sm() as s:
        rows = (await s.execute(
            text(f"{_USER_SELECT} {where} ORDER BY u.usuario_red LIMIT :lim"),  # noqa: S608
            {**params, "lim": MAX_EXPORT_ROWS + 1})).mappings().all()
    truncated = len(rows) > MAX_EXPORT_ROWS
    rows = rows[:MAX_EXPORT_ROWS]
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        uow.audit(AuditEntry(categoria="EXPORTACION", accion="USR_EXPORTED", modulo="ADM",
                             entidad="usuario",
                             detalle={"filtros": f.model_dump(mode="json", exclude_none=True),
                                      "filas": len(rows), "truncado": truncated}))
        await uow.commit()
    content = build_xlsx("usuarios", EXPORT_COLUMNS,
                         ([r[c] for c in EXPORT_COLUMNS] for r in rows))
    return xlsx_response(content, "secureone-usuarios.xlsx", truncated)


class UsuarioDetalleOut(UsuarioOut):
    modulos: list[str]


async def _audit_view(auth: AuthService, request: Request, p: Principal, accion: str,
                      user_id: uuid.UUID) -> None:
    async with UnitOfWork(auth.sm, audit_context(request, p), auth.spool) as uow:
        uow.audit(AuditEntry(categoria="CONSULTA", accion=accion, modulo="ADM",
                             entidad="usuario", entidad_id=str(user_id)))
        await uow.commit()


@router.get("/admin/users/{user_id}", response_model=UsuarioDetalleOut)
async def get_user(
    user_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(require("ADM.USUARIO.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> UsuarioDetalleOut:
    async with auth.sm() as s:
        row = (await s.execute(text(f"{_USER_SELECT} WHERE u.id = :id"),  # noqa: S608
                               {"id": user_id})).mappings().first()
        if row is None:
            raise NotFoundError()
        modulos = (await s.execute(text(
            "SELECT m.codigo FROM app.usuario_modulo um JOIN app.modulo m ON m.id = um.modulo_id "
            "WHERE um.usuario_id = :id AND um.estado = 'ACTIVO' ORDER BY m.orden"),
            {"id": user_id})).scalars().all()
    await _audit_view(auth, request, p, "USR_VIEWED", user_id)
    return UsuarioDetalleOut(**row, modulos=list(modulos))


class SesionOut(BaseModel):
    iniciada_en: datetime
    ultima_actividad: datetime
    finalizada_en: datetime | None
    motivo_fin: str | None
    ip: str | None


class ActividadOut(BaseModel):
    ultimo_ingreso: datetime | None
    ultima_actividad: datetime | None
    intentos_fallidos: int
    bloqueado_hasta: datetime | None
    sesion_activa: bool
    sesiones: list[SesionOut]


@router.get("/admin/users/{user_id}/activity", response_model=ActividadOut)
async def get_user_activity(
    user_id: uuid.UUID,
    request: Request,
    p: Principal = Depends(require("ADM.USUARIO.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> ActividadOut:
    """REQ-AUTH-16 / M §11.3: último ingreso, historial, intentos fallidos y sesión activa."""
    async with auth.sm() as s:
        head = (await s.execute(text(
            "SELECT u.ultimo_ingreso, u.ultima_actividad, c.intentos_fallidos, c.bloqueado_hasta "
            "FROM app.usuario u LEFT JOIN app.credencial c ON c.usuario_id = u.id "
            "WHERE u.id = :id"), {"id": user_id})).mappings().first()
        if head is None:
            raise NotFoundError()
        sesiones = (await s.execute(text(
            "SELECT iniciada_en, ultima_actividad, finalizada_en, motivo_fin, host(ip) AS ip "
            "FROM app.sesion WHERE usuario_id = :id ORDER BY iniciada_en DESC LIMIT 20"),
            {"id": user_id})).mappings().all()
    await _audit_view(auth, request, p, "USR_ACTIVITY_VIEWED", user_id)
    return ActividadOut(
        ultimo_ingreso=head["ultimo_ingreso"],
        ultima_actividad=head["ultima_actividad"],
        intentos_fallidos=head["intentos_fallidos"] or 0,
        bloqueado_hasta=head["bloqueado_hasta"],
        sesion_activa=any(x["finalizada_en"] is None for x in sesiones),
        sesiones=[SesionOut(**x) for x in sesiones],
    )


class HistItemOut(BaseModel):
    atributo: str
    valor_anterior: Any
    valor_nuevo: Any


class HistSolicitudOut(BaseModel):
    numero: int
    tipo: str
    estado: str
    motivo: str | None
    creada_en: datetime
    solicitante: str | None
    resuelta_en: datetime | None
    resuelta_por: str | None
    motivo_resolucion: str | None
    solicitud_vinculada: int | None
    items: list[HistItemOut]


class HistEstadoOut(BaseModel):
    estado_anterior: str | None
    estado_nuevo: str
    motivo: str
    actor: str | None
    solicitud: int | None
    ocurrido_en: datetime


class HistorialOut(BaseModel):
    solicitudes: list[HistSolicitudOut]
    estados: list[HistEstadoOut]


@router.get("/admin/users/{user_id}/history", response_model=HistorialOut)
async def get_user_history(
    user_id: uuid.UUID,
    _: Principal = Depends(require("ADM.USUARIO.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> HistorialOut:
    """REQ-USER-08 / D-APR-002: historial por atributo (ítems de cada solicitud con su
    resolución) e historial de estados con actor, fecha y motivo."""
    async with auth.sm() as s:
        if not (await s.execute(text("SELECT 1 FROM app.usuario WHERE id = :u"),
                                {"u": user_id})).first():
            raise NotFoundError()
        sols = (await s.execute(text(
            "SELECT so.id, so.numero, so.tipo, so.estado, so.motivo, so.creada_en, "
            "us.usuario_red AS solicitante, so.resuelta_en, ur.usuario_red AS resuelta_por, "
            "so.motivo_resolucion, sv.numero AS solicitud_vinculada "
            "FROM app.solicitud so LEFT JOIN app.usuario us ON us.id = so.solicitante_id "
            "LEFT JOIN app.usuario ur ON ur.id = so.resuelta_por_id "
            "LEFT JOIN app.solicitud sv ON sv.id = so.solicitud_vinculada_id "
            "WHERE so.entidad = 'usuario' AND so.entidad_id = :u ORDER BY so.numero"),
            {"u": user_id})).mappings().all()
        items = (await s.execute(text(
            "SELECT solicitud_id, atributo, valor_anterior, valor_nuevo FROM app.solicitud_item "
            "WHERE solicitud_id = ANY(:ids) ORDER BY orden"),
            {"ids": [x["id"] for x in sols]})).mappings().all()
        estados = (await s.execute(text(
            "SELECT h.estado_anterior, h.estado_nuevo, h.motivo, a.usuario_red AS actor, "
            "so.numero AS solicitud, h.ocurrido_en FROM app.usuario_estado_historial h "
            "LEFT JOIN app.usuario a ON a.id = h.actor_id "
            "LEFT JOIN app.solicitud so ON so.id = h.solicitud_id "
            "WHERE h.usuario_id = :u ORDER BY h.ocurrido_en"), {"u": user_id})).mappings().all()
    by_sol: dict[uuid.UUID, list[HistItemOut]] = {}
    for it in items:
        by_sol.setdefault(it["solicitud_id"], []).append(HistItemOut(
            atributo=it["atributo"], valor_anterior=it["valor_anterior"],
            valor_nuevo=it["valor_nuevo"]))
    return HistorialOut(
        solicitudes=[HistSolicitudOut(**{k: v for k, v in x.items() if k != "id"},
                                      items=by_sol.get(x["id"], [])) for x in sols],
        estados=[HistEstadoOut(**e) for e in estados])
