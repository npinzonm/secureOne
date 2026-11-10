import os

# Valores ficticios SOLO para pruebas unitarias/API sin dependencias reales.
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test-only-not-a-secret")
os.environ.setdefault("REDIS_PASSWORD", "test-only-not-a-secret")
