import os
import tempfile

# Valores ficticios SOLO para pruebas sin dependencias reales. En el ambiente de pruebas
# (docker-compose.test.yml) las variables reales ya vienen definidas y no se sobrescriben.
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("APP_DB_USER", "test_api")
os.environ.setdefault("APP_DB_PASSWORD", "test-only-not-a-secret")
os.environ.setdefault("REDIS_PASSWORD", "test-only-not-a-secret")
os.environ.setdefault("SPOOL_DIR", tempfile.mkdtemp(prefix="secureone-spool-"))

# Las pruebas de integración solo se recolectan dentro del ambiente de pruebas (make test-int).
collect_ignore_glob = [] if os.environ.get("TEST_OWNER_USER") else ["integration/*"]
