# Fase 2 — Fundamentos FastAPI

## Alcance
Base técnica sobre la que se construyen las fases siguientes. **Sin reglas de negocio de usuarios ni IAM.**
1. Acceso a datos con SQLAlchemy 2 (async, psycopg 3) y **migraciones versionadas con Alembic**.
2. **Separación de credenciales de BD:**
   - Rol *owner*: solo para migraciones.
   - Rol de *runtime* `APP_DB_USER`: sin DDL, sin DELETE por defecto y solo INSERT/SELECT sobre auditoría.
   - Servicio `migrate` de una sola ejecución antes del backend.
3. Esquemas `app`, `audit` y `ops`.
4. **Auditoría inmutable y fail-closed:**
   - tabla `audit.evento`;
   - cadena de hash calculada por trigger en la BD;
   - triggers anti UPDATE/DELETE/TRUNCATE;
   - función de verificación;
   - `UnitOfWork` + `AuditWriter`, que insertan el evento en la misma transacción que el cambio;
   - ante un fallo: rollback, 503 y registro de incidente en el *spool* local, que se vuelca a `ops` al recuperarse.
5. **Registro centralizado de errores** `ops.registro_error`, independiente de la transacción fallida y enlazado por `correlation_id`.
6. **Manejo uniforme de errores** (401/403/404/409/422/503/500) con el formato `{"error": {code, message, correlation_id, details?}}`.
7. **Esqueleto de módulos** (`api/application/domain/infrastructure`) para auth, iam, users, org, approvals, audit, errors, notifications, th, params e indicium.
8. Readiness ampliado: verifica también que las migraciones estén en `head`.

## Requisitos cubiertos
- **Completos:** REQ-AUD-02, REQ-AUD-03, REQ-AUD-04, REQ-ERR-01, REQ-ERR-02, REQ-ERR-03, REQ-RNF-02, REQ-RNF-03, REQ-RNF-04.
- **Base técnica:** REQ-AUD-07 (fail-closed), REQ-GEN-04 (modularidad).
- **Decisiones aplicadas:** PD-03 (aislamiento e integridad de la auditoría, PROPUESTO) y PD-04 (APROBADO).

## Archivos principales
| Archivo | Propósito |
|---|---|
| `backend/alembic.ini`, `backend/migrations/` | Migraciones versionadas |
| `backend/migrations/versions/0001_*.py` | Esquemas, auditoría, errores, permisos |
| `backend/app/cli.py` | `migrate` (rol de runtime + Alembic), `flush-incidents`, `audit-verify` |
| `backend/app/core/db.py`, `core/errors.py` | Motor y sesiones; jerarquía de errores y handlers |
| `backend/app/kernel/` | `audit.py`, `unit_of_work.py`, `error_registry.py`, `models.py` |
| `backend/app/modules/*/` | Esqueleto modular |
| `docker-compose*.yml`, `.env.example`, `scripts/init-env.sh` | Servicio `migrate`, credenciales separadas, volumen de *spool* |
| `backend/tests/integration/` | Pruebas contra PostgreSQL real (ambiente test) |

## Criterios de aceptación
1. `make up` aplica las migraciones antes de arrancar el backend; `ready` informa `migrations: ok`.
2. El backend se conecta con el rol de runtime: no puede hacer DDL ni DELETE en `app`, ni UPDATE/DELETE en `audit.evento`.
3. Ni siquiera el owner puede modificar o borrar `audit.evento` (trigger).
4. `audit-verify` informa una cadena íntegra y detecta una manipulación provocada.
5. **Fail-closed:** si la inserción del evento falla, el cambio de negocio no se persiste, la API responde 503 `AUDIT_UNAVAILABLE` y queda un incidente en el spool. Al ejecutar `flush-incidents` con la auditoría restaurada, el incidente pasa a `ops.registro_error` con un evento `OPS_AUDIT_OUTAGE_RECORDED`.
6. Los errores no controlados devuelven 500 con el formato uniforme, sin detalles internos, y se registran en `ops.registro_error` con el mismo `correlation_id`.
7. Los valores antes/después de auditoría nunca contienen claves sensibles (se enmascaran).
8. `make lint`, `make test` (unitarias) y `make test-int` (integración) pasan.

## Resultado (ejecutado el 2026-11-09)

| # | Criterio | Resultado |
|---|---|---|
| 1 | `migrate` antes del backend; `ready` con `migrations: ok` | OK: stack base (volumen de la Fase 1) y ambiente test; `migrate` es idempotente |
| 2 | Rol de runtime sin DDL ni DELETE; sin UPDATE/DELETE/TRUNCATE en auditoría | OK: 7 casos de prueba con `InsufficientPrivilege`; el rol no es superusuario ni crea roles o BD |
| 3 | El owner tampoco modifica la auditoría | OK: UPDATE, DELETE y TRUNCATE bloqueados por trigger |
| 4 | Cadena íntegra y detección de manipulación | OK: la BD fija seq, fecha y hash (ignora los enviados por el cliente); la manipulación se detecta en el seq exacto; `make audit-verify` OK |
| 5 | Fail-closed | OK: con INSERT revocado en auditoría, el cambio de negocio no persiste, se responde 503 `AUDIT_UNAVAILABLE` y queda el incidente en el spool sin datos de negocio; `flush` lo lleva a `ops.registro_error` (AUDITORIA/CRITICA) con `OPS_AUDIT_OUTAGE_RECORDED` |
| 6 | 500 uniforme y registrado con `correlation_id` | OK, sin filtrar detalle interno |
| 7 | Antes/después y diagnóstico sin secretos | OK (enmascarado) |
| 8 | lint / unitarias / integración | OK: `ruff` sin hallazgos; 23 unitarias/API; 18 de integración |

Extra: 0 apariciones de `POSTGRES_PASSWORD` y `APP_DB_PASSWORD` en los logs; el contenedor backend no recibe credenciales owner.

**Limitaciones conocidas (documentadas):**
- La cadena de hash no detecta el borrado del **último** evento si se hace con privilegios de superusuario y triggers deshabilitados. Mitigación futura: anclaje externo periódico del último hash (PD-03).
- El volcado del spool se ejecuta al iniciar el backend y con `app.cli flush-incidents`. El volcado periódico automático llega con el worker (Fase 7).
- El `CREATE/ALTER ROLE ... PASSWORD` del comando `migrate` viaja en una sentencia SQL. PostgreSQL no la registra con la configuración por defecto (`log_statement=none`); no se debe activar `log_statement=all` en el contenedor.
- La tabla `app.zz_prueba` solo existe en la BD efímera del ambiente de pruebas.

**No verificado:** CI en GitHub (la rama no se ha publicado).
