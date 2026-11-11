"""Bandeja interna (CU-NOT-01) y seguimiento de entregas (CU-NOT-02)."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.core.errors import NotFoundError
from app.kernel.authz import require
from app.modules.auth.api.dependencies import get_auth_service, require_session
from app.modules.auth.application.service import AuthService, Principal

router = APIRouter(tags=["notifications"])


class BandejaItem(BaseModel):
    id: uuid.UUID
    asunto: str
    cuerpo: str
    evento: str
    recibida_en: datetime
    leida: bool


class BandejaOut(BaseModel):
    items: list[BandejaItem]
    no_leidas: int


@router.get("/notifications", response_model=BandejaOut)
async def my_inbox(
    solo_no_leidas: bool = False,
    limit: int = Query(50, ge=1, le=200),
    p: Principal = Depends(require_session()),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> BandejaOut:
    """Solo las propias y ya publicadas (ENVIADA)."""
    async with auth.sm() as s:
        rows = (await s.execute(text(
            "SELECT e.id, n.asunto, n.cuerpo, n.evento_origen AS evento, "
            "e.enviada_en AS recibida_en, e.leida_en IS NOT NULL AS leida "
            "FROM ops.entrega_notificacion e JOIN ops.notificacion n ON n.id = e.notificacion_id "
            "WHERE e.usuario_id = :u AND e.canal = 'BANDEJA' AND e.estado = 'ENVIADA' "
            "AND (NOT :solo OR e.leida_en IS NULL) ORDER BY e.enviada_en DESC LIMIT :l"),
            {"u": p.user_id, "solo": solo_no_leidas, "l": limit})).mappings().all()
        unread = (await s.execute(text(
            "SELECT count(*) FROM ops.entrega_notificacion WHERE usuario_id = :u "
            "AND canal = 'BANDEJA' AND estado = 'ENVIADA' AND leida_en IS NULL"),
            {"u": p.user_id})).scalar_one()
    return BandejaOut(items=[BandejaItem(**r) for r in rows], no_leidas=unread)


@router.post("/notifications/{delivery_id}/read", status_code=204)
async def mark_read(
    delivery_id: uuid.UUID,
    p: Principal = Depends(require_session()),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> None:
    async with auth.sm() as s, s.begin():
        done = (await s.execute(text(
            "UPDATE ops.entrega_notificacion SET leida_en = coalesce(leida_en, now()) "
            "WHERE id = :i AND usuario_id = :u AND canal = 'BANDEJA' AND estado = 'ENVIADA' "
            "RETURNING id"), {"i": delivery_id, "u": p.user_id})).first()
    if done is None:  # ajena o inexistente: indistinguible (no revela existencia)
        raise NotFoundError()


class EntregaOut(BaseModel):
    id: uuid.UUID
    asunto: str
    evento: str
    destinatario: str
    canal: str
    estado: str
    intentos: int
    ultimo_error: str | None
    proximo_intento_en: datetime
    enviada_en: datetime | None
    creada_en: datetime


@router.get("/admin/notifications/deliveries", response_model=list[EntregaOut])
async def deliveries(
    estado: Literal["PENDIENTE", "ENVIADA", "AGOTADA"] | None = None,
    canal: Literal["BANDEJA", "CORREO"] | None = None,
    limit: int = Query(100, ge=1, le=500),
    _: Principal = Depends(require("ADM.NOTIFICACION.CONSULTA")),  # noqa: B008
    auth: AuthService = Depends(get_auth_service),  # noqa: B008
) -> list[EntregaOut]:
    async with auth.sm() as s:
        rows = (await s.execute(text(
            "SELECT e.id, n.asunto, n.evento_origen AS evento, u.usuario_red AS destinatario, "
            "e.canal, e.estado, e.intentos, e.ultimo_error, e.proximo_intento_en, e.enviada_en, "
            "n.creada_en FROM ops.entrega_notificacion e "
            "JOIN ops.notificacion n ON n.id = e.notificacion_id "
            "JOIN app.usuario u ON u.id = e.usuario_id "
            "WHERE (CAST(:e AS text) IS NULL OR e.estado = :e) "
            "AND (CAST(:c AS text) IS NULL OR e.canal = :c) "
            "ORDER BY n.creada_en DESC LIMIT :l"),
            {"e": estado, "c": canal, "l": limit})).mappings().all()
    return [EntregaOut(**r) for r in rows]
