# Fase 10 — Pruebas integrales, respaldos, documentación y endurecimiento

Rama: `feature/fase-10-endurecimiento`, creada desde `feature/fase-9-frontend`.

## Alcance
| Bloque | Contenido | Requisitos |
|---|---|---|
| **Respaldos** | Servicio `backup`: `pg_dump` diario automático a la hora `BACKUP_HOUR` (America/Bogota); rotación **7 diarios / 4 semanales / 3 mensuales** (M §15.2); SHA-256 por archivo; registro en `ops.registro_respaldo` y en la auditoría. Respaldo manual antes de actualizar (`make backup`, `make update`). **Restauración probada** (`make restore`) con verificación de checksum y de la cadena de auditoría | REQ-RNF-08, M §15 |
| **E2E de navegador** | Playwright en un contenedor contra el ambiente de pruebas; integrado en el CI | REQ-RNF-05 |
| **Endurecimiento** | CSP completa en Nginx; auditoría de dependencias (`pip-audit`, `npm audit`) en el CI; Dependabot | REQ-RNF-01 |
| **Documentación** | Manual de operación: levantar, detener, migrar, bootstrap, pruebas, respaldo/restauración, rotación de secretos y diagnóstico. Matriz de trazabilidad (`docs/trazabilidad.csv`) con los campos de M §24 | REQ-RNF-07, REQ-RNF-11 |

## Decisiones aplicadas
- **PD-26 (PROPUESTO → implementado):** `pg_dump -Fc` y rotación de M §15.2.
- **No se fijan RPO ni RTO** (REQ-RNF-12 pendiente).
- **Cifrado de respaldos:** no implementado. Queda como recomendación (clave fuera del repositorio) porque no hay un gestor de claves aprobado.
- **TLS local (PD-20):** sigue pendiente. La CSP y las cabeceras no dependen de él.

## Criterios de aceptación
1. El servicio `backup` arranca *healthy*, ejecuta el respaldo diario a la hora configurada y genera `.dump` + `.sha256`.
2. La rotación conserva exactamente 7 diarios, 4 semanales y 3 mensuales (probado con fechas simuladas).
3. Cada respaldo y cada restauración quedan en `ops.registro_respaldo` y en `audit.evento`.
4. Restaurar un respaldo devuelve la BD al estado respaldado (los datos posteriores desaparecen) y la cadena de auditoría queda íntegra. Un checksum alterado impide la restauración.
5. Las E2E de Playwright pasan en contenedor:
   - login fallido y válido;
   - cambio obligatorio de contraseña;
   - recarga con sesión recuperada;
   - alta desde TH con aprobación y contraseña temporal;
   - aviso de inactividad;
   - logout y redirección de rutas protegidas.
6. La CSP no rompe la aplicación (sin violaciones en la consola) y bloquea scripts externos.
7. `pip-audit` y `npm audit --audit-level=high` sin hallazgos (o hallazgos documentados).
8. Todas las suites anteriores siguen pasando.

## Resultado (2026-11-11)
### Pruebas ejecutadas
| Suite | Resultado |
|---|---|
| `make lint` (ruff) | OK |
| `make test` (unitarias/API) | 66 aprobadas (incluye `test_route_discovery_is_not_empty`) |
| `make test-int` (PostgreSQL/Redis reales) | 87 aprobadas |
| `make test-e2e` (Playwright 1.64.1, Chromium) | 8/8 aprobadas: login fallido genérico, cambio obligatorio de temporal, recarga con refresh HttpOnly/Strict sin token en storage, alta TH → autoaprobación → temporal de una sola vez, perfil de sistema protegido y menú filtrado, aviso de inactividad, logout + refresh 401, CSP sin violaciones |
| `make test-backups` | 17/17 verificaciones: rotación 7/4/3 en 100 días simulados, registro en `ops.registro_respaldo` y auditoría, checksum alterado rechazado (código 3, sin restaurar), restauración elimina datos posteriores, cadena de auditoría íntegra, backend sano |
| `pip-audit` / `npm audit` | Sin vulnerabilidades conocidas |
| Frontend `tsc` + `next build` | OK |
| Stack base | Migración 0007 → 0008 aplicada; 8 servicios *healthy* (incluido `backup`); `make health` OK; respaldo diario y manual registrados; `make audit-verify` íntegro; sin secretos en logs |

### Endurecimiento aplicado
- **Dependencias actualizadas por vulnerabilidades:** FastAPI 0.162.0 / Starlette 1.10.0, PyJWT 2.15.1, python-multipart 0.0.32, postcss 8.5.31 (override; Next incluía 8.4.31) y @playwright/test 1.64.1.
- **Cambio de FastAPI:** los routers incluidos ya no se copian a `app.routes`. Las meta-pruebas de autorización (T-SEC-00) usan `tests/route_utils.py` (`iter_route_contexts`) y exigen un mínimo de 60 rutas para no pasar en vacío.
- **Cabeceras:** CSP (`default-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri`/`form-action 'self'`) y `Cross-Origin-Opener-Policy: same-origin`. `'unsafe-inline'` en scripts y estilos se mantiene porque Next.js emite scripts inline de hidratación; endurecerlo con *nonces* requiere renderizado dinámico (mejora futura).
- **CI:** jobs `security` (pip-audit, npm audit) y `e2e-and-backups`; Dependabot semanal (pip/npm) y mensual (Docker/Actions).
- **Operación:** [manual de operación](../operacion/MANUAL-OPERACION.md) y matriz de trazabilidad [docs/trazabilidad.csv](../trazabilidad.csv), generada por `scripts/generate-trazabilidad.py`. Resultado: 124 requisitos; 113 implementados, 2 parciales (Indicium), 8 no aplican (aplazados o excluidos) y 1 pendiente (REQ-RNF-12).

### Limitaciones y pendientes
- Respaldos **sin cifrar** y en el mismo equipo: copiar `BACKUP_DIR` fuera del equipo es un procedimiento manual (manual §4).
- RPO/RTO, disponibilidad y retención técnica **no fijados** (REQ-RNF-12, PENDIENTE: no se inventan métricas).
- TLS local (PD-20) pendiente.
- DD-01..DD-07 definidas por delegación: deben validarse con TH y con una especificación UX.
