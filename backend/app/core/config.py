"""Configuración por variables de entorno (REQ-RNF-06).

Los secretos se declaran como SecretStr para que nunca se impriman en logs ni en repr().
No hay valores por defecto para secretos: si faltan, la aplicación no arranca.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "prod"
    log_level: str = "INFO"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: SecretStr

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: SecretStr

    health_timeout_seconds: float = 2.0

    @property
    def postgres_dsn(self) -> str:
        pwd = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"postgresql://{quote(self.postgres_user, safe='')}:{pwd}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
