# Fase 1 — Repositorio y entorno Docker Compose reproducible

## Alcance
Esqueleto ejecutable de los 5 servicios (nginx, frontend, backend, postgres, redis) con health checks, configuración por variables de entorno, secretos fuera del repositorio, redes aisladas y CI básico. **Sin lógica de negocio.**

Fuera de alcance de esta fase:
- worker, mailpit, backup → Fases 7 y 10;
- migraciones Alembic → Fase 2;
- TLS → pendiente de PD-20.

## Requisitos cubiertos
REQ-GEN-01, REQ-GEN-05, REQ-GEN-10, REQ-RNF-06, REQ-RNF-09 (parcial: dev y test), REQ-RNF-10 (parcial: CI), REQ-RNF-01 (parcial: contenedores sin root y cabeceras de seguridad).

## Archivos creados

| Archivo | Propósito |
|---|---|
| `.gitignore`, `.dockerignore`, `.env.example` | Exclusión de secretos; plantilla sin valores |
| `scripts/init-env.sh` | Genera `.env` con secretos aleatorios (no sobrescribe) |
| `docker-compose.yml` | Stack base (equivale al ambiente "prod" local) |
| `docker-compose.dev.yml` | Override de desarrollo (recarga en caliente, puerto de BD local) |
| `docker-compose.test.yml` | Ambiente de pruebas aislado (proyecto y volúmenes propios) |
| `Makefile` | `up`, `down`, `logs`, `ps`, `test`, `health` |
| `backend/` | FastAPI mínimo: `/api/v1/health/live`, `/api/v1/health/ready`, config, logging JSON, pruebas |
| `frontend/` | Next.js mínimo (standalone): página inicial + `/healthz` |
| `infra/nginx/` | Proxy inverso sin privilegios, cabeceras, bloqueo de `/health/ready` desde fuera |
| `.github/workflows/ci.yml` | Lint, pruebas y construcción + smoke test del stack |
| `README.md` | Levantar, detener, probar |

## Criterios de aceptación
1. `./scripts/init-env.sh && make up` levanta los 5 servicios y todos quedan `healthy`.
2. `GET http://localhost:8080/` sirve la página del frontend.
3. `GET http://localhost:8080/api/v1/health/live` → 200.
4. `GET http://localhost:8080/api/v1/health/ready` desde fuera → 404 (bloqueado por Nginx). Desde dentro de la red → 200 con PostgreSQL y Redis OK.
5. Con PostgreSQL o Redis detenido, el *ready* interno → 503.
6. Solo Nginx publica un puerto; postgres y redis no son accesibles desde el host (salvo el override dev para postgres en 127.0.0.1).
7. Ningún secreto está en archivos versionados; Compose falla si falta una variable obligatoria.
8. Las pruebas del backend pasan dentro del contenedor.
9. Los contenedores de aplicación corren como usuario no root.

## Resultado (ejecutado el 2026-11-09, macOS arm64, Docker 29.9.3 / Compose v5.7.0)

| # | Criterio | Resultado |
|---|---|---|
| 1 | Los 5 servicios `healthy` desde cero | OK (arranque en ~33 s con las imágenes ya construidas) |
| 2 | Frontend vía Nginx | OK 200 |
| 3 | `/api/v1/health/live` | OK 200 |
| 4 | `ready` externo bloqueado / interno OK | OK 404 / 200 |
| 5 | `ready` con PostgreSQL o Redis caído | OK 503 en ambos casos, sin detalle del error; vuelve a 200 al recuperarse |
| 6 | Solo Nginx publica un puerto (127.0.0.1) | OK; 5432 y 6379 cerrados en el host (base) |
| 7 | Sin secretos versionados; falla sin variable obligatoria | OK; `.env` ignorado por Git; Compose aborta con un mensaje claro |
| 8 | Pruebas del backend | OK: `ruff` sin hallazgos, `pytest` 11/11 |
| 9 | Procesos no root | OK: backend uid 10001, frontend 1000, nginx 101 |
| extra | Logs sin secretos | OK: 0 apariciones de las contraseñas de `.env` |
| extra | Ambiente de pruebas aislado en paralelo (8081) | OK |
| extra | Override de desarrollo | OK (docs en `/api/v1/docs`, BD en 127.0.0.1:5432) |

**No verificado:** el workflow de GitHub Actions (aún no hay repositorio remoto, PD-13).

**Incidencias corregidas:**
- Compose suma los `ports` de los overrides → se usa `!override` en test.
- El bash 3.2 de macOS falla con un arreglo vacío y `set -u` en `smoke.sh`.
- ruff y pytest intentaban escribir caché en un FS de solo lectura.

**Observación:** en la primera construcción completa, `compose up --wait` dejó a Nginx en `Created` hasta que se inició manualmente. En arranques posteriores desde cero no se repitió.
