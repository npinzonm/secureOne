# SecureOne v1.0 — Prototipo local

Plataforma modular de Seguridad de la Información y Ciberseguridad.
Stack: Next.js · FastAPI · PostgreSQL · Redis · Nginx · Docker Compose · GitHub Actions.

> Estado: **Fase 1 (infraestructura) implementada.** Sin lógica de negocio todavía.
> El diseño técnico (PROPUESTO, pendiente de validación) está en [`docs/`](docs/00-README.md).

## Requisitos
- Docker Desktop (o un motor compatible) con Docker Compose v2.
- `make`, `openssl`, `curl` (incluidos en macOS).

## Primer arranque
```bash
make up          # genera .env con secretos aleatorios (si no existe) y levanta el stack
make health      # smoke test: frontend, API, readiness y cabeceras
```
Abrir: <http://127.0.0.1:8080>. Solo Nginx publica un puerto, y solo en `127.0.0.1`.

## Operación diaria

| Acción | Comando |
|---|---|
| Levantar (base / "prod" local) | `make up` |
| Levantar en desarrollo (recarga en caliente, docs en `/api/v1/docs`, BD en `127.0.0.1:5432`) | `make up-dev` |
| Detener (conserva datos) | `make down` / `make down-dev` |
| Estado / logs | `make ps` / `make logs` |
| Lint y pruebas del backend | `make lint` / `make test` |
| Ambiente de pruebas aislado (puerto 8081, datos efímeros) | `make test-stack` y luego `make test-stack-down` |

**Borrar todos los datos locales** (irreversible): `docker compose down -v`.

## Secretos
- `.env` lo genera `scripts/init-env.sh` con contraseñas aleatorias y permisos `600`. No se versiona.
- `.env.example` es solo una plantilla, sin valores reales.
- Compose se niega a arrancar si falta una variable obligatoria.

## Estructura
```text
backend/     FastAPI (app/, tests/)
frontend/    Next.js (src/app)
infra/nginx/ Proxy inverso
scripts/     init-env.sh, smoke.sh
docs/        Diseño técnico, especificaciones y fases
```

## Pendiente en fases siguientes
Migraciones (Fase 2) · bootstrap de administradores y autenticación (Fase 3) · respaldo y restauración (Fase 10) · TLS local (PD-20).
