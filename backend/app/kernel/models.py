"""Metadatos SQLAlchemy compartidos y tablas del kernel.

Las tablas del kernel se declaran con Core (Table) porque `audit.evento` tiene columnas
que solo fija la BD (seq, ocurrido_en, hash). El esquema real lo define la migración 0001;
estas declaraciones solo sirven para construir consultas.
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "%(table_name)s_%(column_0_name)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


audit_evento = Table(
    "evento",
    Base.metadata,
    Column("seq", BigInteger, primary_key=True),
    Column("id", UUID(as_uuid=True), nullable=False),
    Column("ocurrido_en", DateTime(timezone=True)),
    Column("actor_id", UUID(as_uuid=True)),
    Column("actor_usuario_red", String(64)),
    Column("actor_tipo", String(16), nullable=False),
    Column("categoria", String(32), nullable=False),
    Column("modulo", String(16)),
    Column("accion", String(64), nullable=False),
    Column("entidad", String(64)),
    Column("entidad_id", String(64)),
    Column("valor_anterior", JSONB),
    Column("valor_nuevo", JSONB),
    Column("resultado", String(16), nullable=False),
    Column("motivo", Text),
    Column("ip_origen", INET),
    Column("user_agent", String(512)),
    Column("detalle", JSONB),
    Column("correlation_id", String(64)),
    Column("solicitud_id", UUID(as_uuid=True)),
    Column("hash_previo", LargeBinary),
    Column("hash", LargeBinary),
    schema="audit",
)

ops_registro_error = Table(
    "registro_error",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("ocurrido_en", DateTime(timezone=True)),
    Column("categoria", String(32), nullable=False),
    Column("modulo", String(16)),
    Column("componente", String(64), nullable=False),
    Column("actor_id", UUID(as_uuid=True)),
    Column("proceso", String(64)),
    Column("tipo", String(128), nullable=False),
    Column("severidad", String(8), nullable=False),
    Column("descripcion", Text, nullable=False),
    Column("diagnostico", JSONB),
    Column("estado_atencion", String(16)),
    Column("correlation_id", String(64)),
    Column("atendido_por", UUID(as_uuid=True)),
    Column("atendido_en", DateTime(timezone=True)),
    schema="ops",
)
