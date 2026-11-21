# SecureOne v1.0 — Manual de operación

Ambiente objetivo: computador personal o universitario con **Docker Desktop** (o un motor compatible con Compose v2), `make`, `openssl`, `curl` y `python3`.

> Todos los comandos se ejecutan desde la raíz del repositorio. `make help` no existe: los objetivos disponibles están en el `Makefile`, con su descripción.

## 1. Primer despliegue
```bash
make up                 # genera .env con secretos aleatorios (si no existe), construye, migra y levanta
make health             # smoke test: frontend, API, readiness interna y cabeceras de seguridad
make bootstrap-admin    # crea el 1.er administrador (interactivo); repetir para el 2.º (máximo 2)
```
- `make bootstrap-admin` muestra **una sola vez** la contraseña temporal. Entréguela por un canal seguro; se cambia obligatoriamente en el primer inicio de sesión.
- Aplicación: <http://127.0.0.1:8080>. Correos del prototipo (Mailpit): <http://127.0.0.1:8025>.
- Los catálogos de gerencias, áreas y cargos **solo** se cargan desde Talento Humano (Administración → Talento Humano → cargar la planta activa). Sin ellos no se pueden crear altas de usuarios.

## 2. Operación diaria
| Tarea | Comando |
|---|---|
| Estado de los servicios | `make ps` |
| Logs (JSON, sin secretos) | `make logs` (o `docker compose logs -f backend`) |
| Detener sin borrar datos | `make down` |
| Volver a levantar | `make up` |
| Verificar la integridad de la auditoría | `make audit-verify` |
| Volcar incidentes de auditoría pendientes | `docker compose exec backend python -m app.cli flush-incidents` (el worker lo hace cada minuto) |

**Servicios:**
- `nginx`: único puerto, 127.0.0.1:8080.
- `frontend` y `backend`.
- `migrate`: se ejecuta una vez al levantar.
- `worker`: notificaciones, procesamiento TH, alertas y sesiones abandonadas.
- `backup`: respaldos diarios.
- `postgres` y `redis`.
- `mailpit`: SMTP local del prototipo.

## 3. Actualización de versión
```bash
git pull
make update     # 1) respaldo MANUAL "pre-actualizacion"  2) reconstruye  3) aplica migraciones y levanta
make health && make audit-verify
```
Las migraciones son versionadas (Alembic) y las aplica el servicio `migrate` con el rol owner. El backend **no arranca** si la BD no está en la última revisión (*readiness* `migrations: fail`).

## 4. Respaldos y restauración (REQ-RNF-08)
| Aspecto | Detalle |
|---|---|
| Automático | Diario a `BACKUP_HOUR` (por defecto 02:00, zona `BACKUP_TZ` = America/Bogota) |
| Retención (M §15.2) | 7 diarios · 4 semanales (domingo) · 3 mensuales (día 1) |
| Ubicación | `BACKUP_DIR` (por defecto `./backups/{daily,weekly,monthly,manual}`), excluido de Git |
| Formato | `pg_dump -Fc` + archivo `.sha256` |
| Registro | `ops.registro_respaldo` y auditoría (`OPS_BACKUP_CREATED`, `OPS_RESTORE_EXECUTED`) |
| Manual | `make backup LABEL=antes-de-x` (los manuales no se rotan: elimínelos cuando ya no se necesiten) |

**Restaurar:**
```bash
make restore FILE=backups/daily/2026-11-11.dump
```
1. Pide escribir `RESTAURAR`.
2. Verifica el SHA-256. Si no coincide, **no restaura**.
3. Detiene nginx, backend y worker.
4. Toma un respaldo manual `pre-restauracion` del estado actual.
5. Restaura con `pg_restore --clean`.
6. Vuelve a levantar (migraciones a head) y verifica la cadena de auditoría.

**Consideraciones:**
- La restauración **reemplaza toda la BD**, incluidos los registros de respaldo posteriores al respaldo restaurado. Los archivos siguen en disco.
- Copie periódicamente `BACKUP_DIR` fuera del equipo (disco externo o almacenamiento institucional). Un respaldo en el mismo disco no protege contra la pérdida del equipo.
- Los respaldos **no están cifrados** en v1.0: proteja la carpeta (contiene datos personales y hashes de contraseñas).
- La prueba automatizada de rotación y restauración es `make test-backups` (ambiente de pruebas).

## 5. Pruebas
| Suite | Comando | Ambiente |
|---|---|---|
| Lint + unitarias/API | `make lint` · `make test` | Contenedor, sin dependencias |
| Integración (PostgreSQL/Redis reales) | `make test-int` | `secureone_test` (efímero) |
| E2E de navegador (Playwright) | `make test-e2e` | `secureone_test` (puerto 8081) |
| Respaldos (rotación y restauración) | `make test-backups` | `secureone_test` |
| Detener el ambiente de pruebas | `make test-stack-down` | Borra sus datos efímeros |

El ambiente de pruebas usa su propio proyecto, volúmenes y puertos (8081/8026): no toca los datos del stack base.

## 6. Secretos
- `.env` lo genera `scripts/init-env.sh` (permisos 600) y **no se versiona**. `.env.example` es solo una plantilla.
- **Rotación del secreto JWT:** cambiar `JWT_SECRET` en `.env` y ejecutar `docker compose up -d backend worker`. Todas las sesiones quedan inválidas y los usuarios vuelven a iniciar sesión.
- **Rotación de la contraseña del rol de runtime:** cambiar `APP_DB_PASSWORD` en `.env` y ejecutar `make up`. El servicio `migrate` actualiza la contraseña del rol antes de que arranque el backend.
- **Contraseña de un administrador olvidada:** el otro administrador genera una temporal desde la ficha del usuario. Si no hay otro administrador activo, `make bootstrap-admin` solo funciona mientras haya menos de 2 administradores activos.

## 7. Diagnóstico
| Síntoma | Causa probable | Acción |
|---|---|---|
| Login responde 503 `AUDIT_UNAVAILABLE` | La auditoría no puede escribirse (fail-closed) | Revisar `postgres`; al recuperarse, el worker registra el incidente en Errores |
| 503 en cualquier petición autenticada | Redis caído (sesiones, fail-closed) | `docker compose restart redis`; los usuarios vuelven a iniciar sesión |
| `ready` con `migrations: fail` | Código más nuevo que la BD | `make migrate` |
| Correos sin enviar | SMTP no disponible | Administración → Entregas (reintentos 1/5/15/60 min); la bandeja interna sigue funcionando |
| Planta TH en `FALLIDA` | Falla técnica tras 3 reintentos | Ver Errores; volver a cargar el archivo indicando el reproceso y el motivo |
| Alta rechazada: «no figura en la última planta» | Regla DD-02 (NORMAL) | Tramitar como EXCEPCIONAL con motivo, o esperar la planta de TH |
| 429 en el login | Límite de Nginx (10/min por IP) | Esperar un minuto |

## 8. Limitaciones conocidas de v1.0
- Sin TLS local (PD-20 pendiente): las cookies `Secure` funcionan en `http://127.0.0.1` (contexto seguro del navegador).
- Respaldos sin cifrar; sin RPO/RTO definidos (REQ-RNF-12).
- Contrato TH y UX definidos por delegación (DD-03..DD-07): deben revisarse con TH y con una especificación UX.
- Indicium Insight: solo el contenedor del módulo (reglas aplazadas, D-IND-001).
