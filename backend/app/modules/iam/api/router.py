"""Consultas IAM (Fase 4). Las operaciones que modifican datos llegan en la Fase 5 (PD-05).

E.2 (/me/*) y E.4/E.6 (consultas) de docs/04-api-endpoints.md.
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.kernel.authz import require
from app.modules.auth.api.dependencies import get_auth_service, require_session
from app.modules.auth.application.service import AuthService, Principal

router = APIRouter(tags=["iam"])

NO_MODULES_MESSAGE = (
    "No tiene módulos asignados. Contacte a un administrador de SecureOne."  # PROPUESTO
)
Estado = Literal["ACTIVO", "INACTIVO"]


async def _rows(auth: AuthService, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
    async with auth.sm() as s:
        return [dict(r) for r in (await s.execute(text(sql), params or {})).mappings()]


# ---------------------------------------------------------------------------- /me

class ModuloOut(BaseModel):
    codigo: str
    nombre: str
    descripcion: str | None
    ruta_frontend: str
    orden: int


class MisModulosOut(BaseModel):
    modulos: list[ModuloOut]
    mensaje: str | None


@router.get("/me/modules", response_model=MisModulosOut)
async def my_modules(
    p: Principal = Depends(require_session()),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> MisModulosOut:
    """REQ-IAM-12/13: solo módulos asignados y activos, en el orden global."""
    rows = await _rows(
        auth,
        """
        SELECT m.codigo, m.nombre, m.descripcion, m.ruta_frontend, m.orden
          FROM app.usuario_modulo um JOIN app.modulo m ON m.id = um.modulo_id
         WHERE um.usuario_id = :u AND um.estado = 'ACTIVO' AND m.estado = 'ACTIVO'
         ORDER BY m.orden
        """,
        {"u": p.user_id},
    )
    return MisModulosOut(modulos=[ModuloOut(**r) for r in rows],
                         mensaje=None if rows else NO_MODULES_MESSAGE)


@router.get("/me/permissions", response_model=list[str])
async def my_permissions(
    p: Principal = Depends(require_session()),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[str]:
    """Solo para presentar la UI: la autorización real ocurre en cada endpoint."""
    rows = await _rows(auth, "SELECT permiso FROM app.v_permiso_efectivo "
                             "WHERE usuario_id = :u ORDER BY permiso", {"u": p.user_id})
    return [r["permiso"] for r in rows]


# ---------------------------------------------------------------------------- /admin IAM

class PerfilOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None
    estado: str
    es_sistema: bool
    roles: list[str]
    usuarios_activos: int


@router.get("/admin/profiles", response_model=list[PerfilOut])
async def list_profiles(
    _: Principal = Depends(require("ADM.PERFIL.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[PerfilOut]:
    rows = await _rows(
        auth,
        """
        SELECT pf.id, pf.codigo, pf.nombre, pf.descripcion, pf.estado, pf.es_sistema,
               COALESCE(array_agg(r.codigo ORDER BY r.codigo)
                        FILTER (WHERE r.codigo IS NOT NULL), '{}') AS roles,
               (SELECT count(*) FROM app.usuario u
                 WHERE u.perfil_id = pf.id AND u.estado = 'ACTIVO') AS usuarios_activos
          FROM app.perfil pf
          LEFT JOIN app.perfil_rol pr ON pr.perfil_id = pf.id AND pr.estado = 'ACTIVO'
          LEFT JOIN app.rol r ON r.id = pr.rol_id
         GROUP BY pf.id ORDER BY pf.codigo
        """,
    )
    return [PerfilOut(**r) for r in rows]


class RolOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None
    estado: str
    es_sistema: bool
    permisos: list[str]


@router.get("/admin/roles", response_model=list[RolOut])
async def list_roles(
    _: Principal = Depends(require("ADM.ROL.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[RolOut]:
    rows = await _rows(
        auth,
        """
        SELECT r.id, r.codigo, r.nombre, r.descripcion, r.estado, r.es_sistema,
               COALESCE(array_agg(p.codigo ORDER BY p.codigo)
                        FILTER (WHERE p.codigo IS NOT NULL), '{}') AS permisos
          FROM app.rol r
          LEFT JOIN app.rol_permiso rp ON rp.rol_id = r.id AND rp.estado = 'ACTIVO'
          LEFT JOIN app.permiso p ON p.id = rp.permiso_id
         GROUP BY r.id ORDER BY r.codigo
        """,
    )
    return [RolOut(**r) for r in rows]


class PermisoOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None
    modulo: str
    categoria: str
    estado: str
    es_sistema: bool


@router.get("/admin/permissions", response_model=list[PermisoOut])
async def list_permissions(
    modulo: str | None = Query(None, max_length=16),
    categoria: Literal["CONSULTA", "CREACION", "EDICION", "ELIMINACION", "APROBACION",
                       "EXPORTACION"] | None = None,
    estado: Estado | None = None,
    _: Principal = Depends(require("ADM.PERMISO.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[PermisoOut]:
    rows = await _rows(
        auth,
        """
        SELECT p.id, p.codigo, p.nombre, p.descripcion, m.codigo AS modulo, p.categoria,
               p.estado, p.es_sistema
          FROM app.permiso p JOIN app.modulo m ON m.id = p.modulo_id
         WHERE (CAST(:m AS text) IS NULL OR m.codigo = :m)
           AND (CAST(:c AS text) IS NULL OR p.categoria = :c)
           AND (CAST(:e AS text) IS NULL OR p.estado = :e)
         ORDER BY p.codigo
        """,
        {"m": modulo, "c": categoria, "e": estado},
    )
    return [PermisoOut(**r) for r in rows]


class ModuloAdminOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None
    estado: str
    orden: int
    ruta_frontend: str
    es_sistema: bool
    usuarios_asignados: int


@router.get("/admin/modules", response_model=list[ModuloAdminOut])
async def list_modules(
    _: Principal = Depends(require("ADM.MODULO.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[ModuloAdminOut]:
    rows = await _rows(
        auth,
        """
        SELECT m.id, m.codigo, m.nombre, m.descripcion, m.estado, m.orden, m.ruta_frontend,
               m.es_sistema,
               (SELECT count(*) FROM app.usuario_modulo um
                 WHERE um.modulo_id = m.id AND um.estado = 'ACTIVO') AS usuarios_asignados
          FROM app.modulo m ORDER BY m.orden
        """,
    )
    return [ModuloAdminOut(**r) for r in rows]


class DominioOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    descripcion: str | None
    modulo: str | None
    estado: str


@router.get("/admin/domains", response_model=list[DominioOut])
async def list_domains(
    _: Principal = Depends(require("ADM.DOMINIO.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[DominioOut]:
    rows = await _rows(
        auth,
        "SELECT d.id, d.codigo, d.nombre, d.descripcion, m.codigo AS modulo, d.estado "
        "FROM app.dominio d LEFT JOIN app.modulo m ON m.id = d.modulo_id ORDER BY d.codigo",
    )
    return [DominioOut(**r) for r in rows]


# ---------------------------------------------------------------------------- catálogos org

class CatalogoOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str
    estado: str


class AreaOut(CatalogoOut):
    gerencia_id: uuid.UUID


class CargoOut(BaseModel):
    id: uuid.UUID
    codigo_cargo: int
    nombre: str
    estado: str


@router.get("/admin/org/managements", response_model=list[CatalogoOut])
async def list_managements(
    estado: Estado | None = None,
    _: Principal = Depends(require("ADM.ORG.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[CatalogoOut]:
    rows = await _rows(auth, "SELECT id, codigo, nombre, estado FROM app.gerencia "
                             "WHERE (CAST(:e AS text) IS NULL OR estado = :e) ORDER BY nombre",
                       {"e": estado})
    return [CatalogoOut(**r) for r in rows]


@router.get("/admin/org/areas", response_model=list[AreaOut])
async def list_areas(
    management_id: uuid.UUID | None = None,
    estado: Estado | None = None,
    _: Principal = Depends(require("ADM.ORG.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[AreaOut]:
    """REQ-USER-06: seleccionar la gerencia filtra sus áreas."""
    rows = await _rows(
        auth,
        "SELECT id, codigo, nombre, estado, gerencia_id FROM app.area "
        "WHERE (CAST(:g AS uuid) IS NULL OR gerencia_id = :g) "
        "AND (CAST(:e AS text) IS NULL OR estado = :e) ORDER BY nombre",
        {"g": management_id, "e": estado},
    )
    return [AreaOut(**r) for r in rows]


@router.get("/admin/org/positions", response_model=list[CargoOut])
async def list_positions(
    estado: Estado | None = None,
    _: Principal = Depends(require("ADM.ORG.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[CargoOut]:
    rows = await _rows(auth, "SELECT id, codigo_cargo, nombre, estado FROM app.cargo "
                             "WHERE (CAST(:e AS text) IS NULL OR estado = :e) "
                             "ORDER BY codigo_cargo", {"e": estado})
    return [CargoOut(**r) for r in rows]
