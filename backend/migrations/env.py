"""Entorno Alembic. Las migraciones se ejecutan SIEMPRE con el rol owner.

El nombre del rol de runtime llega por `config.attributes["app_db_user"]` (desde app.cli)
o por la variable APP_DB_USER, para que las migraciones otorguen privilegios sin
codificar nombres ni contraseñas.
"""

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import MigrationSettings
from app.kernel.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("owner_url")
    if url:
        return url
    return MigrationSettings().owner_sqlalchemy_url  # type: ignore[call-arg]


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
