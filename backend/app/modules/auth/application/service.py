"""Casos de uso de autenticación (ESP-AUTH: CU-AUTH-01..04, 09).

Todas las operaciones que generan eventos de autenticación usan UnitOfWork (fail-closed,
PD-04 APROBADO): si la auditoría falla, nada se persiste y se responde 503.
Las claves de Redis se escriben ANTES del commit (si el commit falla, se limpian), para que
nunca exista en BD una sesión cerrada cuya clave siga viva en Redis.
"""

import dataclasses
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.domain.errors import (
    AccountLockedError,
    InvalidCredentialsError,
    InvalidCurrentPasswordError,
    PasswordChangeRequiredError,
    PasswordPolicyError,
    SessionEndedError,
)
from app.modules.auth.domain.password_policy import password_policy_violations
from app.modules.auth.infrastructure import repository as repo
from app.modules.auth.infrastructure.hashing import (
    dummy_verify,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.modules.auth.infrastructure.session_store import SessionStore
from app.modules.auth.infrastructure.tokens import (
    InvalidTokenError,
    decode_access_token,
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
)
from app.modules.users.domain.identifiers import is_valid_usuario_red, normalize_usuario_red

logger = logging.getLogger(__name__)
CAT = "AUTENTICACION"


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    usuario_red: str
    session_id: uuid.UUID
    restricted: bool


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    must_change_password: bool
    refresh_token: str | None


class AuthService:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        store: SessionStore,
        spool: IncidentSpool,
    ) -> None:
        self.settings = settings
        self.sm = sessionmaker
        self.store = store
        self.spool = spool

    # ------------------------------------------------------------------ helpers
    def _uow(self, ctx: AuditContext) -> UnitOfWork:
        return UnitOfWork(self.sm, ctx, self.spool)

    def _access(self, uid: uuid.UUID, sid: uuid.UUID, restricted: bool) -> str:
        return issue_access_token(
            self.settings.jwt_secret.get_secret_value(),
            uid,
            sid,
            "pwchange" if restricted else "access",
            self.settings.access_token_ttl_seconds,
        )

    # ------------------------------------------------------------------ CU-AUTH-01 login
    async def login(
        self, usuario_red_raw: str, password: str, ip: str | None, ua: str | None
    ) -> IssuedTokens:
        red = normalize_usuario_red(usuario_red_raw)
        await self.store.ping()  # Redis caído → 503 antes de tocar nada (fail-closed)
        ctx = AuditContext(ip_origen=ip, user_agent=ua)
        now = datetime.now(UTC)

        async with self._uow(ctx) as uow:
            row = await repo.get_for_login(uow.session, red)

            if row is None:
                dummy_verify(password)
                uow.audit(AuditEntry(
                    categoria=CAT, accion="AUTH_LOGIN_FAILED", resultado="FALLO",
                    detalle={
                        "motivo": "USUARIO_DESCONOCIDO",
                        "usuario_red": red if is_valid_usuario_red(red) else None,
                    },
                ))
                await uow.commit()
                raise InvalidCredentialsError()

            uow.ctx = dataclasses.replace(ctx, actor_id=row.user_id, actor_usuario_red=red)

            if row.estado != "ACTIVO":
                dummy_verify(password)
                uow.audit(AuditEntry(
                    categoria=CAT, accion="AUTH_LOGIN_REJECTED", resultado="DENEGADO",
                    entidad="usuario", entidad_id=str(row.user_id),
                    detalle={"motivo": f"ESTADO_{row.estado}"},
                ))
                await uow.commit()
                raise InvalidCredentialsError()

            if row.bloqueado_hasta is not None and row.bloqueado_hasta > now:
                uow.audit(AuditEntry(
                    categoria=CAT, accion="AUTH_LOGIN_REJECTED", resultado="DENEGADO",
                    entidad="usuario", entidad_id=str(row.user_id),
                    detalle={"motivo": "BLOQUEO_TEMPORAL"},
                ))
                await uow.commit()
                raise AccountLockedError()

            if not verify_password(row.password_hash, password):
                # Un bloqueo vencido no arrastra intentos previos.
                base = 0 if row.bloqueado_hasta is not None else row.intentos_fallidos
                attempts = base + 1
                locked = attempts >= self.settings.lockout_threshold
                lock_delta = timedelta(minutes=self.settings.lockout_minutes)
                locked_until = now + lock_delta if locked else None
                await repo.register_failure(
                    uow.session, row.user_id, 0 if locked else attempts, locked_until
                )
                uow.audit(AuditEntry(
                    categoria=CAT, accion="AUTH_LOGIN_FAILED", resultado="FALLO",
                    entidad="usuario", entidad_id=str(row.user_id),
                    detalle={"motivo": "CONTRASENA_INVALIDA", "intento": attempts},
                ))
                if locked:
                    uow.audit(AuditEntry(
                        categoria=CAT, accion="AUTH_LOCKOUT", resultado="DENEGADO",
                        entidad="usuario", entidad_id=str(row.user_id),
                        detalle={"minutos": self.settings.lockout_minutes},
                    ))
                await uow.commit()
                raise AccountLockedError() if locked else InvalidCredentialsError()

            # Éxito
            new_hash = hash_password(password) if needs_rehash(row.password_hash) else None
            await repo.reset_failures(uow.session, row.user_id, new_hash)
            previous = await repo.close_open_session(uow.session, row.user_id, "REEMPLAZADA")
            restricted = row.debe_cambiar
            sid = await repo.create_session(uow.session, row.user_id, restricted, ip, ua)
            refresh_raw = None
            if not restricted:
                refresh_raw = new_refresh_token()
                await repo.insert_refresh(uow.session, sid, uuid.uuid4(),
                                          hash_refresh_token(refresh_raw))
            if previous is not None:
                uow.audit(AuditEntry(
                    categoria=CAT, accion="AUTH_SESSION_REPLACED", entidad="sesion",
                    entidad_id=str(previous), detalle={"nueva_sesion": str(sid)},
                ))
            uow.audit(AuditEntry(
                categoria=CAT, accion="AUTH_LOGIN_SUCCESS", entidad="sesion", entidad_id=str(sid),
                detalle={"debe_cambiar_contrasena": restricted},
            ))
            await self.store.open(row.user_id, sid, previous)
            try:
                await uow.commit()
            except Exception:
                await self._safe_close(row.user_id, sid)
                raise

        return IssuedTokens(
            access_token=self._access(row.user_id, sid, restricted),
            expires_in=self.settings.access_token_ttl_seconds,
            must_change_password=restricted,
            refresh_token=refresh_raw,
        )

    async def _safe_close(self, uid: uuid.UUID, sid: uuid.UUID) -> None:
        try:
            await self.store.close(uid, sid)
        except Exception as exc:  # noqa: BLE001
            logger.error("no se pudo limpiar la sesión en Redis (%s)", type(exc).__name__)

    # ------------------------------------------------------------------ autenticación por petición
    async def authenticate(
        self, token: str | None, *, allow_restricted: bool, touch: bool = True
    ) -> Principal:
        if not token:
            raise SessionEndedError("Autenticación requerida.")
        try:
            claims = decode_access_token(self.settings.jwt_secret.get_secret_value(), token)
        except InvalidTokenError as exc:
            raise SessionEndedError() from exc

        uid, sid = claims.user_id, claims.session_id
        if not await self.store.is_active(uid, sid):
            await self._end_if_open(uid, sid, "INACTIVIDAD", "AUTH_SESSION_EXPIRED")
            raise SessionEndedError()

        async with self.sm() as s:
            state = await repo.get_user_state(s, uid)
        if state is None or state[0] != "ACTIVO":
            await self.store.close(uid, sid)
            await self._end_if_open(uid, sid, "INHABILITACION", "AUTH_SESSION_REVOKED")
            raise SessionEndedError()

        restricted = claims.typ == "pwchange"
        if restricted and not allow_restricted:
            raise PasswordChangeRequiredError()

        if touch and await self.store.touch(uid, sid):
            async with self.sm() as s, s.begin():
                await repo.touch_activity(s, uid, sid)

        return Principal(uid, state[1], sid, restricted)

    async def _end_if_open(self, uid: uuid.UUID, sid: uuid.UUID, motivo: str, accion: str) -> None:
        async with self._uow(AuditContext(actor_id=uid)) as uow:
            if not await repo.close_session(uow.session, sid, motivo):
                return
            uow.audit(AuditEntry(categoria=CAT, accion=accion, entidad="sesion",
                                 entidad_id=str(sid), detalle={"motivo": motivo}))
            await uow.commit()

    # ------------------------------------------------------------------ CU-AUTH-02 refresh
    async def refresh(self, raw: str | None) -> IssuedTokens:
        if not raw:
            raise SessionEndedError()
        await self.store.ping()
        token_hash = hash_refresh_token(raw)

        async with self.sm() as s, s.begin():
            row = await repo.get_refresh_for_update(s, token_hash)
            if row is None:
                raise SessionEndedError()
            reused = row.usado_en is not None or row.revocado_en is not None
            if not reused:
                usable = (
                    row.sesion_finalizada is None
                    and row.usuario_estado == "ACTIVO"
                    and await self.store.is_active(row.usuario_id, row.sesion_id)
                )
                if not usable:
                    raise SessionEndedError()
                new_raw = new_refresh_token()
                new_id = await repo.insert_refresh(s, row.sesion_id, row.familia_id,
                                                   hash_refresh_token(new_raw))
                await repo.mark_refresh_used(s, row.id, new_id)

        if reused:
            # Reutilización: posible robo del refresh → se revoca la sesión completa.
            await self.store.close(row.usuario_id, row.sesion_id)
            async with self._uow(AuditContext(actor_id=row.usuario_id)) as uow:
                await repo.close_session(uow.session, row.sesion_id, "REUSO_REFRESH")
                uow.audit(AuditEntry(
                    categoria=CAT, accion="AUTH_REFRESH_REUSE", resultado="DENEGADO",
                    entidad="sesion", entidad_id=str(row.sesion_id),
                ))
                await uow.commit()
            raise SessionEndedError()

        return IssuedTokens(
            access_token=self._access(row.usuario_id, row.sesion_id, False),
            expires_in=self.settings.access_token_ttl_seconds,
            must_change_password=False,
            refresh_token=new_raw,
        )

    # ------------------------------------------------------------------ CU-AUTH-03 logout
    async def logout(self, p: Principal, ctx: AuditContext) -> None:
        await self.store.close(p.user_id, p.session_id)
        async with self._uow(ctx) as uow:
            await repo.close_session(uow.session, p.session_id, "LOGOUT")
            uow.audit(AuditEntry(categoria=CAT, accion="AUTH_LOGOUT", entidad="sesion",
                                 entidad_id=str(p.session_id)))
            await uow.commit()

    # ------------------------------------------------------------------ CU-AUTH-04 cambio
    async def change_password(
        self, p: Principal, current: str, new: str, ctx: AuditContext
    ) -> None:
        async with self._uow(ctx) as uow:
            cred = await repo.get_credential(uow.session, p.user_id)
            if cred is None:
                raise SessionEndedError()
            current_hash, usuario_red = cred
            if not verify_password(current_hash, current):
                uow.audit(AuditEntry(
                    categoria=CAT, accion="AUTH_PASSWORD_CHANGE_FAILED", resultado="FALLO",
                    entidad="usuario", entidad_id=str(p.user_id),
                    detalle={"motivo": "CONTRASENA_ACTUAL_INVALIDA"},
                ))
                await uow.commit()
                raise InvalidCurrentPasswordError()

            violations = password_policy_violations(new, usuario_red)
            recent = await repo.recent_password_hashes(
                uow.session, p.user_id, self.settings.password_history
            )
            if any(verify_password(h, new) for h in {current_hash, *recent}):
                violations.append("REUSED_PASSWORD")
            if violations:
                raise PasswordPolicyError(details={"violations": violations})

            await repo.set_password(uow.session, p.user_id, hash_password(new),
                                    must_change=False, keep=self.settings.password_history)
            await repo.close_session(uow.session, p.session_id, "CAMBIO_CONTRASENA")
            uow.audit(AuditEntry(categoria=CAT, accion="AUTH_PASSWORD_CHANGED",
                                 entidad="usuario", entidad_id=str(p.user_id)))
            await self.store.close(p.user_id, p.session_id)
            await uow.commit()

    async def remaining_seconds(self, p: Principal) -> int:
        return await self.store.remaining_seconds(p.session_id)
