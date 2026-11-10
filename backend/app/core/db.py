"""Motor y sesiones de base de datos (SQLAlchemy 2 async + psycopg 3), rol de runtime."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(self, url: str, *, pool_size: int = 5, max_overflow: int = 5) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            connect_args={"connect_timeout": 5},
        )
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False, autoflush=False
        )

    async def dispose(self) -> None:
        await self.engine.dispose()


def get_database(request: Request) -> Database:
    return request.app.state.db


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Sesión de solo lectura para consultas. Las mutaciones usan UnitOfWork."""
    async with request.app.state.db.sessionmaker() as session:
        yield session
