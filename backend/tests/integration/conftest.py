"""Fixtures de integración: PostgreSQL real del ambiente de pruebas (docker-compose.test.yml).

- `owner`: conexión psycopg síncrona con el rol owner (solo en ambiente test) para preparar
  tablas de prueba y simular manipulación o caída de la auditoría.
- `db`: Database con el rol de RUNTIME (el mismo que usa el backend).
"""

import os
from urllib.parse import quote

import psycopg
import pytest

from app.core.config import get_settings
from app.core.db import Database


def owner_dsn() -> str:
    s = get_settings()
    return (
        f"postgresql://{quote(os.environ['TEST_OWNER_USER'], safe='')}:"
        f"{quote(os.environ['TEST_OWNER_PASSWORD'], safe='')}"
        f"@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}"
    )


@pytest.fixture
def owner():
    with psycopg.connect(owner_dsn(), autocommit=True) as conn:
        yield conn


@pytest.fixture
def runtime():
    """Conexión psycopg síncrona con el rol de runtime (para probar privilegios)."""
    with psycopg.connect(get_settings().postgres_dsn, autocommit=True) as conn:
        yield conn


@pytest.fixture
async def db():
    database = Database(get_settings().sqlalchemy_url, pool_size=2, max_overflow=0)
    yield database
    await database.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_table():
    """Tabla de negocio SOLO para pruebas; los privilegios llegan por DEFAULT PRIVILEGES."""
    with psycopg.connect(owner_dsn(), autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app.zz_prueba (id uuid PRIMARY KEY, nombre text NOT NULL)"
        )
    yield
