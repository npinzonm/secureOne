# ESP-AUD · Especificación funcional — Auditoría y gestión de errores

> **Estado del documento: PROPUESTO** (esquema de eventos: REQ-AUD-09 pendiente).

## 1. Principios (APROBADOS)
- La bitácora es central e inmutable: ningún usuario, incluido el administrador, la edita o borra.
- Nunca contiene contraseñas, tokens, secretos ni credenciales.
- **Fail-closed** en operaciones críticas (alcance: PD-04).
- Retención indefinida hasta que exista una política formal.
- Se auditan las consultas sensibles y las exportaciones, no la navegación rutinaria.
- El registro de errores va **separado** de la auditoría y se correlaciona con ella por `correlation_id`.

## 2. Esquema del evento (PROPUESTO)
`id, ocurrido_en (UTC), actor_id, actor_usuario_red, actor_tipo (USUARIO|SISTEMA|TH), categoria, modulo, accion, entidad, entidad_id, valor_anterior, valor_nuevo, resultado (EXITO|FALLO|DENEGADO), motivo, ip_origen, user_agent, detalle, correlation_id, solicitud_id?, hash_previo, hash`.

- `valor_anterior` y `valor_nuevo` pasan por una **lista blanca** de campos por entidad; los campos sensibles nunca se serializan.

## 3. Catálogo de eventos (PROPUESTO)

| Categoría | Eventos |
|---|---|
| Autenticación | AUTH_LOGIN_SUCCESS, AUTH_LOGIN_FAILED, AUTH_LOGIN_REJECTED, AUTH_LOCKOUT, AUTH_LOGOUT, AUTH_SESSION_EXPIRED, AUTH_SESSION_REPLACED, AUTH_SESSION_REVOKED, AUTH_REFRESH_REUSE, AUTH_PASSWORD_CHANGED, AUTH_PASSWORD_RESET, AUTH_BOOTSTRAP |
| Autorización | AUTHZ_DENIED (permiso o módulo y motivo) |
| Usuarios | USR_CREATED, USR_UPDATED, USR_DEACTIVATED, USR_REACTIVATED, USR_VIEWED, USR_ACTIVITY_VIEWED, USR_EXPORTED |
| IAM | IAM_PROFILE_*, IAM_ROLE_*, IAM_ROLE_PERMISSIONS, IAM_PERMISSION_*, IAM_MODULE_*, IAM_MODULE_ORDER, IAM_USER_MODULES, IAM_DOMAIN_* |
| Aprobaciones | APR_REQUEST_CREATED, APR_APPROVED, APR_REJECTED, APR_CANCELLED, APR_SUPERSEDED |
| TH | TH_FILE_RECEIVED, TH_DUPLICATE_REJECTED, TH_EXECUTION_COMPLETED, TH_EXECUTION_REJECTED, TH_RETRY_EXHAUSTED, TH_ALERT_RAISED, TH_CATALOG_SYNCED, TH_FILE_PURGED |
| Auditoría | AUD_QUERIED, AUD_EXPORTED, AUD_VERIFIED |
| Administración | PAR_UPDATED, ERR_STATUS_CHANGED |
| Operación | OPS_BACKUP_*, OPS_RESTORE_*, OPS_AUDIT_OUTAGE_RECORDED |

## 4. Integridad (PD-03)
- Esquema `audit` con un rol de escritura que solo tiene INSERT, un rol de lectura con SELECT y triggers que rechazan UPDATE, DELETE y TRUNCATE.
- Cadena de hash por evento. Un comando `audit verify` y el endpoint correspondiente informan la primera ruptura.
- **Serialización de la cadena:** `pg_advisory_xact_lock` al insertar. Es aceptable con el volumen del piloto; no se fija una métrica.

## 5. Fail-closed (PD-04)
1. El evento se inserta en la **misma transacción** que el cambio de negocio.
2. Si el INSERT falla, se hace rollback total y se responde **503** `AUDIT_UNAVAILABLE`.
3. El incidente se escribe en un archivo local de contingencia (volumen `ops`). El worker lo vuelca a `ops.registro_error` y emite `OPS_AUDIT_OUTAGE_RECORDED` cuando vuelve la conexión (P §9.1).

## 6. Registro de errores (APROBADO, M §12)
- **Categorías:** autenticación, validaciones, CRUD, automatizaciones, notificaciones, integraciones, base de datos, infraestructura, respaldos, recuperación y auditoría (añadida, PROPUESTA).
- **Severidad (PROPUESTO):** BAJA, MEDIA, ALTA, CRÍTICA.
- **Estado de atención:** ABIERTO, EN_ATENCION, CERRADO.
- El administrador consulta los errores y cambia su estado de atención (auditado); no los borra.
