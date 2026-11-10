# SecureOne v1.0 — Prototipo local

Plataforma modular de Seguridad de la Información y Ciberseguridad.
Stack: Next.js · FastAPI · PostgreSQL · Redis · Nginx · Docker Compose · GitHub Actions.

> Estado: **Fases 1–4 implementadas** (infraestructura, fundamentos, autenticación y sesiones, IAM con autorización por operación y consultas administrativas). Las operaciones administrativas que modifican datos llegan en la Fase 5.
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
| Lint y pruebas del backend | `make lint` / `make test` (unitarias) / `make test-int` (integración, PostgreSQL real) |
| Aplicar migraciones manualmente | `make migrate` (también se ejecutan solas en `make up`) |
| Verificar integridad de la auditoría | `make audit-verify` |
| Volcar incidentes de auditoría pendientes | `docker compose exec backend python -m app.cli flush-incidents` |
| Ambiente de pruebas aislado (puerto 8081, datos efímeros) | `make test-stack` y luego `make test-stack-down` |

**Borrar todos los datos locales** (irreversible): `docker compose down -v`.

## Administradores iniciales (bootstrap)
Con el stack levantado, crear cada administrador (máximo 2):
```bash
make bootstrap-admin
```
- Pide usuario de red, identificación, nombre, apellidos y correo. No hay valores por defecto.
- Muestra **una sola vez** una contraseña temporal aleatoria: entrégala por un canal seguro.
- En el primer inicio de sesión hay que cambiarla (mín. 12 caracteres, con mayúscula, minúscula, número y carácter especial; sin contener el usuario de red; sin repetir ninguna de las 5 últimas).
- Un tercer administrador se rechaza, tanto en la CLI como en la BD.

## Autenticación (API)
| Endpoint | Uso |
|---|---|
| `POST /api/v1/auth/login` | `{usuario_red, password}` → `access_token` (5 min) y cookie de refresh `HttpOnly` |
| `POST /api/v1/auth/refresh` | Rota el refresh y emite un nuevo access token |
| `POST /api/v1/auth/password/change` | Cambio de contraseña (obligatorio con la temporal); cierra la sesión |
| `POST /api/v1/auth/logout` | Cierra la sesión |
| `GET /api/v1/auth/session` · `GET /api/v1/me` | Estado de la sesión / información propia |

La sesión se cierra tras 15 min sin actividad; solo hay una sesión activa por usuario; al 5.º intento fallido la cuenta queda bloqueada 15 min.

## Base de datos
- `POSTGRES_USER` (owner): solo lo usan PostgreSQL y el servicio `migrate`.
- `APP_DB_USER` (runtime): lo crea `migrate`; es el único rol que usa el backend. No puede hacer DDL ni borrados físicos, y en la auditoría solo puede insertar y leer.
- Esquemas: `app` (negocio), `audit` (bitácora inmutable con cadena de hash) y `ops` (errores).

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
Operaciones administrativas y aprobaciones (Fases 5–6, requieren PD-05) · respaldo y restauración (Fase 10) · TLS local (PD-20).
