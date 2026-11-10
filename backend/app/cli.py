"""CLI operativa del backend.

    python -m app.cli migrate          # rol de runtime + migraciones (owner)
    python -m app.cli flush-incidents  # vuelca el spool de incidentes de auditoría a ops
    python -m app.cli audit-verify     # verifica la cadena de hash de audit.evento
    python -m app.cli bootstrap-admin  # crea un administrador (máx. 2) con contraseña temporal

Ningún comando imprime contraseñas.
"""

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import text

from app.core.config import MigrationSettings, get_settings
from app.core.db import Database
from app.core.logging import configure_logging
from app.kernel.audit import IncidentSpool
from app.modules.auth.application.bootstrap import AdminData, BootstrapError, bootstrap_admin

logger = logging.getLogger("secureone.cli")
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def ensure_runtime_role(ms: MigrationSettings) -> None:
    """Rol de runtime: LOGIN, sin superusuario, sin crear BD/roles, sin herencia."""
    role = ms.app_db_user
    if not _ROLE_RE.match(role):
        raise SystemExit("APP_DB_USER inválido: use minúsculas, dígitos y '_' (máx. 63)")
    if role == ms.postgres_user:
        raise SystemExit("APP_DB_USER debe ser distinto de POSTGRES_USER (owner)")
    attrs = sql.SQL("LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS")
    pwd = sql.Literal(ms.app_db_password.get_secret_value())
    with psycopg.connect(ms.owner_dsn, autocommit=True, connect_timeout=10) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        verb = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
        conn.execute(
            sql.SQL("{} {} WITH {} PASSWORD {}").format(verb, sql.Identifier(role), attrs, pwd)
        )
    logger.info("rol de runtime %s: %s", role, "actualizado" if exists else "creado")


def cmd_migrate() -> int:
    ms = MigrationSettings()  # type: ignore[call-arg]
    ensure_runtime_role(ms)
    cfg = alembic_config()
    cfg.attributes["owner_url"] = ms.owner_sqlalchemy_url
    cfg.attributes["app_db_user"] = ms.app_db_user
    command.upgrade(cfg, "head")
    logger.info("migraciones aplicadas hasta head")
    return 0


async def _flush() -> int:
    settings = get_settings()
    db = Database(settings.sqlalchemy_url, pool_size=1, max_overflow=0)
    try:
        n = await IncidentSpool(settings.spool_dir).flush(db.sessionmaker)
    finally:
        await db.dispose()
    logger.info("incidentes de auditoría volcados: %d", n)
    return 0


async def _verify() -> int:
    settings = get_settings()
    db = Database(settings.sqlalchemy_url, pool_size=1, max_overflow=0)
    try:
        async with db.sessionmaker() as s:
            row = (await s.execute(text("SELECT * FROM audit.verificar_cadena()"))).one()
    finally:
        await db.dispose()
    if row.primer_seq_invalido is None:
        print(f"Cadena de auditoría íntegra: {row.total} eventos.")
        return 0
    print(f"CADENA ALTERADA: primer evento inválido seq={row.primer_seq_invalido} "
          f"(total {row.total}).")
    return 1


_ADMIN_FIELDS = [
    ("usuario_red", "Usuario de red (8 caracteres alternados letra/número)", True),
    ("identificacion", "Identificación", True),
    ("nombre", "Nombre", True),
    ("primer_apellido", "Primer apellido", True),
    ("segundo_apellido", "Segundo apellido (opcional)", False),
    ("correo", "Correo", True),
]


async def _bootstrap(values: dict[str, str | None]) -> int:
    settings = get_settings()
    db = Database(settings.sqlalchemy_url, pool_size=1, max_overflow=0)
    try:
        temp = await bootstrap_admin(settings, db.sessionmaker, IncidentSpool(settings.spool_dir),
                                     AdminData(**values))  # type: ignore[arg-type]
    except BootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        await db.dispose()
    # Se imprime SOLO en la terminal del operador (stdout), nunca en logs ni auditoría.
    print("\nAdministrador creado. Contraseña temporal (se muestra una sola vez):\n")
    print(f"    {temp}\n")
    print("Entréguela por un canal seguro. Deberá cambiarse en el primer inicio de sesión.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_argument(
        "command", choices=["migrate", "flush-incidents", "audit-verify", "bootstrap-admin"]
    )
    for name, _, _ in _ADMIN_FIELDS:
        parser.add_argument(f"--{name.replace('_', '-')}", dest=name)
    args = parser.parse_args(argv)
    configure_logging("WARNING" if args.command == "bootstrap-admin" else "INFO")
    if args.command == "migrate":
        return cmd_migrate()
    if args.command == "flush-incidents":
        return asyncio.run(_flush())
    if args.command == "bootstrap-admin":
        values: dict[str, str | None] = {}
        for name, label, required in _ADMIN_FIELDS:
            value = getattr(args, name)
            if value is None:
                value = input(f"{label}: ").strip() or None
            if required and not value:
                print(f"ERROR: {label} es obligatorio", file=sys.stderr)
                return 2
            values[name] = value
        return asyncio.run(_bootstrap(values))
    return asyncio.run(_verify())


if __name__ == "__main__":
    sys.exit(main())
