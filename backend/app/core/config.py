"""Configuración por variables de entorno (REQ-RNF-06).

Los secretos se declaran como SecretStr para que nunca se impriman en logs ni en repr().
No hay valores por defecto para secretos: si faltan, la aplicación no arranca.

Credenciales de base de datos (Fase 2):
- APP_DB_USER / APP_DB_PASSWORD: rol de *runtime* del backend (sin DDL, sin DELETE por defecto).
- POSTGRES_USER / POSTGRES_PASSWORD: rol *owner*; solo lo usa el comando de migración.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _dsn(driver: str, user: str, password: SecretStr, host: str, port: int, db: str) -> str:
    pwd = quote(password.get_secret_value(), safe="")
    return f"{driver}://{quote(user, safe='')}:{pwd}@{host}:{port}/{quote(db, safe='')}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "prod"
    log_level: str = "INFO"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str
    app_db_user: str
    app_db_password: SecretStr

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: SecretStr

    health_timeout_seconds: float = 2.0
    # Directorio local de contingencia para incidentes de auditoría (REQ-AUD-07).
    spool_dir: str = "/var/lib/secureone/spool"

    # Autenticación (PD-01 APROBADO; valores de P §5 APROBADOS).
    jwt_secret: SecretStr
    access_token_ttl_seconds: int = 300          # PD-01: 5 min
    session_idle_seconds: int = 900              # P §5: 15 min de inactividad
    lockout_threshold: int = 5                   # P §5: 5.º intento
    lockout_minutes: int = 15                    # P §5: 15 min
    password_history: int = 5                    # P §5: últimas cinco
    refresh_cookie_secure: bool = True           # PD-18/PD-20

    # Correo (PD-11 PROPUESTO): SMTP configurable; Mailpit en el prototipo local.
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_from: str = "secureone@localhost.test"
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_timeout_seconds: float = 10.0
    worker_poll_seconds: float = 5.0
    # Archivos TH en tránsito (DD-05): volumen temporal; se eliminan al procesarse.
    th_dir: str = "/var/lib/secureone/th"

    @property
    def postgres_dsn(self) -> str:
        """DSN libpq del rol de runtime (psycopg directo)."""
        return _dsn(
            "postgresql", self.app_db_user, self.app_db_password,
            self.postgres_host, self.postgres_port, self.postgres_db,
        )

    @property
    def sqlalchemy_url(self) -> str:
        return _dsn(
            "postgresql+psycopg", self.app_db_user, self.app_db_password,
            self.postgres_host, self.postgres_port, self.postgres_db,
        )


class MigrationSettings(BaseSettings):
    """Solo para `app.cli migrate`: credenciales del owner + rol de runtime a crear."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr
    app_db_user: str
    app_db_password: SecretStr

    @property
    def owner_dsn(self) -> str:
        return _dsn(
            "postgresql", self.postgres_user, self.postgres_password,
            self.postgres_host, self.postgres_port, self.postgres_db,
        )

    @property
    def owner_sqlalchemy_url(self) -> str:
        return _dsn(
            "postgresql+psycopg", self.postgres_user, self.postgres_password,
            self.postgres_host, self.postgres_port, self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
