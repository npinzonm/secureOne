"""Bootstrap seguro de administradores (REQ-AUTH-13, ESP-AUTH R14; CU-AUTH-08).

- Solo en despliegue, desde la CLI (no hay endpoint).
- Sin credenciales codificadas ni valores por defecto: la contraseña temporal es aleatoria,
  se devuelve UNA vez al operador y queda `debe_cambiar = true`.
- Máximo 2 administradores activos (validado aquí y por trigger en BD).
- Auditado con actor SISTEMA (fail-closed).
"""

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.ids import uuid7
from app.kernel.audit import AuditContext, AuditEntry, IncidentSpool
from app.kernel.unit_of_work import UnitOfWork
from app.modules.auth.domain.password_policy import generate_temporary_password
from app.modules.auth.infrastructure import repository as repo
from app.modules.auth.infrastructure.hashing import hash_password
from app.modules.users.domain.identifiers import (
    is_valid_identificacion,
    is_valid_usuario_red,
    normalize_usuario_red,
)

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
MAX_ADMINS = 2


class BootstrapError(Exception):
    pass


@dataclass(frozen=True)
class AdminData:
    usuario_red: str
    identificacion: str
    nombre: str
    primer_apellido: str
    correo: str
    segundo_apellido: str | None = None

    def validated(self) -> "AdminData":
        red = normalize_usuario_red(self.usuario_red)
        errors = []
        if not is_valid_usuario_red(red):
            errors.append("usuario de red: 8 caracteres alternados letra/número")
        if not is_valid_identificacion(self.identificacion.strip()):
            errors.append("identificación: 3–20 caracteres alfanuméricos o '-'")
        if not self.nombre.strip() or len(self.nombre) > 100:
            errors.append("nombre: obligatorio, máx. 100")
        if not self.primer_apellido.strip() or len(self.primer_apellido) > 50:
            errors.append("primer apellido: obligatorio, máx. 50")
        if self.segundo_apellido and len(self.segundo_apellido) > 50:
            errors.append("segundo apellido: máx. 50")
        if not EMAIL_RE.match(self.correo.strip()) or len(self.correo) > 150:
            errors.append("correo: formato inválido")
        if errors:
            raise BootstrapError("; ".join(errors))
        return AdminData(
            usuario_red=red,
            identificacion=self.identificacion.strip(),
            nombre=self.nombre.strip(),
            primer_apellido=self.primer_apellido.strip(),
            correo=self.correo.strip(),
            segundo_apellido=(self.segundo_apellido or "").strip() or None,
        )


async def count_active_admins(s: AsyncSession) -> int:
    return (
        await s.execute(
            text(
                "SELECT count(*) FROM app.usuario u JOIN app.perfil p ON p.id = u.perfil_id "
                "WHERE p.codigo = 'ADMINISTRADOR' AND u.estado = 'ACTIVO'"
            )
        )
    ).scalar_one()


async def bootstrap_admin(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    spool: IncidentSpool,
    data: AdminData,
) -> str:
    d = data.validated()
    temp = generate_temporary_password()
    uid = uuid7()
    async with UnitOfWork(sessionmaker, AuditContext.system(), spool) as uow:
        s = uow.session
        if await count_active_admins(s) >= MAX_ADMINS:
            raise BootstrapError("ya existen dos administradores activos (máximo permitido)")
        dup = (
            await s.execute(
                text("SELECT usuario_red = :r, identificacion = :i FROM app.usuario "
                     "WHERE usuario_red = :r OR identificacion = :i"),
                {"r": d.usuario_red, "i": d.identificacion},
            )
        ).first()
        if dup:
            raise BootstrapError("el usuario de red o la identificación ya existen")
        perfil_id = (
            await s.execute(text("SELECT id FROM app.perfil WHERE codigo = 'ADMINISTRADOR'"))
        ).scalar_one()
        await s.execute(
            text(
                """
                INSERT INTO app.usuario (id, usuario_red, identificacion, nombre, primer_apellido,
                                         segundo_apellido, correo, perfil_id, estado)
                VALUES (:id, :r, :i, :n, :a1, :a2, :c, :p, 'ACTIVO')
                """
            ),
            {"id": uid, "r": d.usuario_red, "i": d.identificacion, "n": d.nombre,
             "a1": d.primer_apellido, "a2": d.segundo_apellido, "c": d.correo, "p": perfil_id},
        )
        pwd_hash = hash_password(temp)
        await s.execute(
            text("INSERT INTO app.credencial (usuario_id, password_hash, debe_cambiar) "
                 "VALUES (:u, :h, true)"),
            {"u": uid, "h": pwd_hash},
        )
        await repo.add_password_history(s, uid, pwd_hash, settings.password_history)
        uow.audit(AuditEntry(
            categoria="AUTENTICACION", accion="AUTH_BOOTSTRAP", modulo="ADM",
            entidad="usuario", entidad_id=str(uid),
            valor_nuevo={"usuario_red": d.usuario_red, "perfil": "ADMINISTRADOR",
                         "estado": "ACTIVO", "debe_cambiar_contrasena": True},
        ))
        try:
            await uow.commit()
        except IntegrityError as exc:
            raise BootstrapError("restricción de BD: " + type(exc.orig).__name__) from exc
    return temp
