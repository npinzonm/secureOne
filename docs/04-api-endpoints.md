# E. Matriz de endpoints

> **PROPUESTA TÉCNICA A VALIDAR — no es el contrato API aprobado** (P §12).
> Base: `/api/v1`. JSON. Errores con formato uniforme `{"error": {"code", "message", "correlation_id", "details?"}}` (REQ-RNF-03).
> **Permisos**: códigos `MOD.RECURSO.CATEGORIA` del [catálogo propuesto](especificaciones/ESP-ADM-IAM.md#catálogo-de-permisos-propuesto). En **Aprob.**: "Sí" = crea una Solicitud y no aplica el cambio (matriz en [ESP-APR](especificaciones/ESP-APR.md#matriz-de-operaciones-propuesta), PD-05).
> **FC** = *fail-closed* respecto de auditoría: si no se puede auditar, responde 503 y no ejecuta.
> **Pruebas**: además de las específicas, **todo endpoint protegido** pasa la batería negativa genérica `T-SEC-*` (sección final).

## E.1 Salud (sin autenticación)

| Método y ruta | Caso de uso | Permiso | Aprob. | Evento | FC | Pruebas |
|---|---|---|---|---|---|---|
| GET `/health/live` | Proceso vivo | — | — | — | — | T-OPS-01 |
| GET `/health/ready` | PostgreSQL, Redis y migraciones al día | — (solo red interna/Nginx) | — | — | — | T-OPS-02 (BD caída → 503) |

## E.2 Autenticación y sesión — módulo `auth`

| Método y ruta | Caso de uso | Permiso | Aprob. | Evento | FC | Pruebas | Req. |
|---|---|---|---|---|---|---|---|
| POST `/auth/login` | CU-AUTH-01 Iniciar sesión | Público | — | `AUTH_LOGIN_SUCCESS` · `AUTH_LOGIN_FAILED` · `AUTH_LOGIN_REJECTED` · `AUTH_LOCKOUT` · `AUTH_SESSION_REPLACED` | Sí | T-AUTH-01..12 | REQ-AUTH-01,07,09,16 |
| POST `/auth/refresh` | CU-AUTH-02 Renovar tokens | Refresh válido | — | `AUTH_REFRESH_REUSE` (solo anomalía) | Sí, en anomalía | T-AUTH-13..16 | REQ-AUTH-14 |
| POST `/auth/logout` | CU-AUTH-03 Cerrar sesión | Autenticado | — | `AUTH_LOGOUT` | Sí | T-AUTH-17 | REQ-AUTH-15 |
| POST `/auth/password/change` | CU-AUTH-04 Cambiar contraseña (obligatorio o voluntario) | Autenticado (también con un token restringido "debe cambiar") | — | `AUTH_PASSWORD_CHANGED` | Sí | T-AUTH-18..24 | REQ-AUTH-03,05 |
| GET `/auth/session` | Estado de la sesión y tiempo restante de inactividad | Autenticado | — | — | — | T-AUTH-25 | REQ-AUTH-08 |
| GET `/me` | CU-USR-08 Consultar la información propia permitida | Autenticado | — | — (no sensible) | — | T-USR-30 | REQ-USER-09 |
| GET `/me/modules` | CU-IAM-10 Módulos asignados y activos, en orden global | Autenticado | — | — | — | T-IAM-30..32 (0 módulos → lista vacía + mensaje) | REQ-IAM-12,13 |
| GET `/me/permissions` | Permisos efectivos (solo para pintar la UI; no autoriza) | Autenticado | — | — | — | T-IAM-33 | REQ-IAM-04 |

## E.3 Usuarios — módulo `ADM`

| Método y ruta | Caso de uso | Permiso | Aprob. | Evento | FC | Pruebas | Req. |
|---|---|---|---|---|---|---|---|
| GET `/admin/users` | CU-USR-01 Consulta central con filtros (sin Empresa) | `ADM.USUARIO.CONSULTA` | — | — (búsqueda rutinaria, D-AUD-001) | — | T-USR-01..04 | REQ-USER-10 |
| GET `/admin/users/{id}` | CU-USR-02 Ver ficha | `ADM.USUARIO.CONSULTA` | — | `USR_VIEWED` (consulta sensible, PD-24) | Sí | T-USR-05 | REQ-AUD-06 |
| POST `/admin/users` | CU-USR-03 Solicitar alta (estado `PENDIENTE_ALTA`) | `ADM.USUARIO.CREACION` | **Sí** | `APR_REQUEST_CREATED` | Sí | T-USR-06..12 (unicidad, patrón, Empresa rechazado) | REQ-USER-01,04,07 |
| PATCH `/admin/users/{id}` | CU-USR-04 Solicitar cambios agrupados | `ADM.USUARIO.EDICION` | **Sí** | `APR_REQUEST_CREATED` | Sí | T-USR-13..16 | REQ-APR-03 |
| POST `/admin/users/{id}/deactivate` | CU-USR-05 Solicitar inhabilitación (motivo obligatorio) | `ADM.USUARIO.ELIMINACION` (lógica) | **Sí** | `APR_REQUEST_CREATED` | Sí | T-USR-17..19 | REQ-USER-08 |
| POST `/admin/users/{id}/reactivate` | CU-USR-06 Solicitar reactivación | `ADM.USUARIO.EDICION` | **Sí** | `APR_REQUEST_CREATED` | Sí | T-USR-20..21 | REQ-AUTH-11, REQ-USER-13 |
| POST `/admin/users/{id}/password-reset` | CU-AUTH-05 Generar contraseña temporal | `ADM.USUARIO.EDICION` | No (PD-05) | `AUTH_PASSWORD_RESET` (sin la contraseña) | Sí | T-AUTH-26..28 | REQ-AUTH-06 |
| POST `/admin/users/{id}/sessions/revoke` | CU-AUTH-06 Cerrar sesión de un usuario | `ADM.USUARIO.EDICION` | No | `AUTH_SESSION_REVOKED` | Sí | T-AUTH-29 | REQ-AUTH-16 |
| GET `/admin/users/{id}/activity` | CU-AUTH-07 Historial de ingresos, intentos y sesiones | `ADM.USUARIO.CONSULTA` | — | `USR_ACTIVITY_VIEWED` | Sí | T-AUTH-30 | REQ-AUTH-16 |
| GET `/admin/users/{id}/history` | Historial de estados y cambios por atributo | `ADM.USUARIO.CONSULTA` | — | — | — | T-USR-22 | REQ-USER-08, REQ-APR-03 |
| PUT `/admin/users/{id}/modules` | CU-IAM-08 Asignar/revocar módulos | `ADM.USUARIO.EDICION` | **Sí** (PD-05) | `APR_REQUEST_CREATED` | Sí | T-IAM-20..22 | REQ-IAM-10 |
| POST `/admin/users/export` | CU-USR-07 Exportar a Excel lo filtrado | `ADM.USUARIO.EXPORTACION` | — | `USR_EXPORTED` (filtros, total) | Sí | T-USR-23..25 (sin columna Empresa) | REQ-USER-11 |

## E.4 IAM — módulo `ADM`

| Método y ruta | Caso de uso | Permiso | Aprob. | Evento | FC | Pruebas | Req. |
|---|---|---|---|---|---|---|---|
| GET/POST `/admin/profiles` | CU-IAM-01 Listar/crear perfil | `ADM.PERFIL.CONSULTA` / `.CREACION` | No (PD-05) | `IAM_PROFILE_CREATED` | Sí | T-IAM-01..03 | REQ-IAM-15 |
| PATCH `/admin/profiles/{id}` | Editar datos y roles del perfil | `ADM.PERFIL.EDICION` | No | `IAM_PROFILE_UPDATED` | Sí | T-IAM-04 | REQ-IAM-09 |
| GET `/admin/profiles/{id}/impact` | Vista previa del impacto (usuarios afectados) | `ADM.PERFIL.CONSULTA` | — | — | — | T-IAM-05 | REQ-IAM-09 |
| POST `/admin/profiles/{id}/status` | Activar/inactivar (bloquea si hay usuarios activos) | `ADM.PERFIL.ELIMINACION` | No | `IAM_PROFILE_STATUS` | Sí | T-IAM-06..07 | REQ-IAM-08 |
| GET/POST `/admin/roles` · PATCH `/admin/roles/{id}` | CU-IAM-02 Gestionar roles | `ADM.ROL.*` | No | `IAM_ROLE_*` | Sí | T-IAM-08..10 | REQ-IAM-15 |
| PUT `/admin/roles/{id}/permissions` | CU-IAM-03 Asignar permisos a un rol (exige `confirm_impact_token`) | `ADM.ROL.EDICION` | No | `IAM_ROLE_PERMISSIONS` (antes/después) | Sí | T-IAM-11..12 | REQ-IAM-09 |
| GET `/admin/roles/{id}/impact` | Impacto en perfiles y usuarios | `ADM.ROL.CONSULTA` | — | — | — | T-IAM-13 | REQ-IAM-09 |
| GET/POST `/admin/permissions` · PATCH `/{id}` · POST `/{id}/status` | CU-IAM-04 Gestionar permisos | `ADM.PERMISO.*` | No | `IAM_PERMISSION_*` | Sí | T-IAM-14..16 (módulo y categoría obligatorios) | REQ-IAM-06,07 |
| GET/POST `/admin/modules` · PATCH `/{id}` | CU-IAM-05 Gestionar módulos | `ADM.MODULO.*` | No | `IAM_MODULE_*` | Sí | T-IAM-17 | REQ-IAM-15 |
| POST `/admin/modules/{id}/status` | Activar/inactivar (la reactivación devuelve las asignaciones históricas a revisar) | `ADM.MODULO.ELIMINACION` | No | `IAM_MODULE_STATUS` | Sí | T-IAM-18..19 | REQ-IAM-11 |
| PUT `/admin/modules/order` | CU-IAM-06 Reordenar módulos | `ADM.MODULO.EDICION` | **No (APROBADO directo)** | `IAM_MODULE_ORDER` | Sí | T-IAM-23 | REQ-IAM-13 |
| GET/POST `/admin/domains` · PATCH `/{id}` | CU-IAM-07 Gestionar dominios (informativo) | `ADM.DOMINIO.*` | No | `IAM_DOMAIN_*` | Sí | T-IAM-24 (no afecta la autorización) | REQ-IAM-14 |

## E.5 Solicitudes — módulo `ADM`

| Método y ruta | Caso de uso | Permiso | Aprob. | Evento | FC | Pruebas | Req. |
|---|---|---|---|---|---|---|---|
| GET `/admin/requests` | CU-APR-01 Bandeja de solicitudes (filtros: estado, tipo, origen) | `ADM.SOLICITUD.CONSULTA` | — | — | — | T-APR-01 | REQ-APR-04 |
| GET `/admin/requests/{id}` | Detalle con ítems y vínculos | `ADM.SOLICITUD.CONSULTA` | — | — | — | T-APR-02 | REQ-APR-04 |
| POST `/admin/requests/{id}/approve` | CU-APR-02 Aprobar y aplicar de forma atómica | `ADM.SOLICITUD.APROBACION` + perfil Administrador | — | `APR_APPROVED` + evento de la operación aplicada (`USR_CREATED`, `USR_DEACTIVATED`, …) | Sí | T-APR-03..10 (autoaprobación OK, sin doble aprobación, versión TH no vigente → 409, snapshot desactualizado → 409, aplicación todo o nada) | REQ-APR-02,03,07,09 |
| POST `/admin/requests/{id}/reject` | CU-APR-03 Rechazar con motivo | `ADM.SOLICITUD.APROBACION` | — | `APR_REJECTED` | Sí | T-APR-11..12 (sin motivo → 422) | REQ-APR-05 |
| POST `/admin/requests/{id}/cancel` | CU-APR-04 Cancelar con motivo (opción: crear solicitud vinculada) | `ADM.SOLICITUD.CREACION` | — | `APR_CANCELLED` | Sí | T-APR-13..15 | REQ-APR-05,06 |
| — (no hay PATCH) | Una solicitud enviada no se edita | — | — | — | — | T-APR-16 (PATCH → 405) | REQ-APR-06 |

## E.6 Auditoría, errores y parámetros — módulo `ADM`

| Método y ruta | Caso de uso | Permiso | Aprob. | Evento | FC | Pruebas | Req. |
|---|---|---|---|---|---|---|---|
| GET `/admin/audit/events` | CU-AUD-01 Consultar la bitácora | `ADM.AUDITORIA.CONSULTA` | — | `AUD_QUERIED` | Sí | T-AUD-01..03 | REQ-AUD-06 |
| POST `/admin/audit/events/export` | CU-AUD-02 Exportar la bitácora | `ADM.AUDITORIA.EXPORTACION` | — | `AUD_EXPORTED` | Sí | T-AUD-04 | REQ-AUD-06 |
| GET `/admin/audit/verify` | CU-AUD-03 Verificar la cadena de integridad | `ADM.AUDITORIA.CONSULTA` | — | `AUD_VERIFIED` | Sí | T-AUD-05..06 (manipulación detectada) | REQ-AUD-04 |
| — (sin PUT/PATCH/DELETE) | Inmutabilidad | — | — | — | — | T-AUD-07..09 (HTTP 405; UPDATE/DELETE SQL rechazado) | REQ-AUD-04 |
| GET `/admin/errors` · PATCH `/admin/errors/{id}` | CU-ERR-01 Consultar errores y cambiar el estado de atención | `ADM.ERROR.CONSULTA` / `.EDICION` | No | `ERR_STATUS_CHANGED` | Sí | T-ERR-01..03 | REQ-ERR-01,02 |
| GET/PATCH `/admin/parameters` | CU-PAR-01 Parámetros generales | `ADM.PARAMETRO.CONSULTA` / `.EDICION` | No (PD-05) | `PAR_UPDATED` | Sí | T-PAR-01 | M §8.2, REQ-TH-06 |
| GET `/admin/org/managements` · `/areas?management_id=` · `/positions` | Catálogos organizacionales (solo lectura) | `ADM.ORG.CONSULTA` | — | — | — | T-ORG-01..03 (sin POST/PATCH → 405) | REQ-USER-06, REQ-TH-13 |

## E.7 Notificaciones (bandeja propia)

| Método y ruta | Caso de uso | Permiso | Evento | Pruebas | Req. |
|---|---|---|---|---|---|
| GET `/notifications` | CU-NOT-01 Bandeja propia | Autenticado (solo las propias) | — | T-NOT-01..02 (no ve las ajenas) | REQ-NOT-01 |
| POST `/notifications/{id}/read` | Marcar como leída | Autenticado, dueño | — | T-NOT-03 | REQ-NOT-01 |
| GET `/admin/notifications/deliveries` | CU-NOT-02 Estado de entregas y reintentos | `ADM.NOTIFICACION.CONSULTA` | — | T-NOT-04..08 (SMTP caído → bandeja OK, reintentos, alerta técnica, operación no revertida) | REQ-NOT-03,04,05 |

## E.8 Integración TH — módulo `ADM` (bloqueada por PD-09)

| Método y ruta | Caso de uso | Permiso | Evento | FC | Pruebas | Req. |
|---|---|---|---|---|---|---|
| POST `/admin/th/files` (multipart: tipo, archivo, motivo_reproceso?, ejecucion_origen_id?) | CU-TH-01 Cargar planta | `ADM.TH.CREACION` | `TH_FILE_RECEIVED`, `TH_DUPLICATE_REJECTED` | Sí | T-TH-01..05 | REQ-TH-01,02,09 |
| GET `/admin/th/executions` · `/{id}` · `/{id}/rows` | CU-TH-02 Consultar ejecuciones, estadísticas y errores | `ADM.TH.CONSULTA` | — | — | T-TH-06 | REQ-TH-08 |
| GET `/admin/th/proposals` · `/{id}` | CU-TH-03 Propuestas versionadas | `ADM.TH.CONSULTA` | — | — | T-TH-07 | REQ-APR-07 |
| POST `/admin/th/proposals/{id}/decide` | CU-TH-04 Decidir alta normal/excepcional de un nuevo funcionario → crea solicitud de alta | `ADM.USUARIO.CREACION` | `APR_REQUEST_CREATED` | Sí | T-TH-08 | REQ-TH-11 |
| GET `/admin/th/alerts` | CU-TH-05 Alertas (ausencia, archivo no recibido) | `ADM.TH.CONSULTA` | — | — | T-TH-09..12 | REQ-TH-05,06 |

## E.9 Indicium Insight (shell)

No hay endpoints de negocio (REQ-IND-02 APLAZADO). El módulo aparece en `/me/modules` si está asignado y activo. La pantalla del frontend muestra el estado "en levantamiento funcional".

---

## E.10 Batería negativa genérica (se aplica a todo endpoint protegido)

Pruebas parametrizadas sobre el registro de rutas de FastAPI. Una prueba de meta-control falla si aparece una ruta protegida sin `require()` (T-SEC-00).

| ID | Escenario | Resultado esperado | Evento |
|---|---|---|---|
| T-SEC-00 | Toda ruta no pública declara `require(perm, module)` | Introspección OK | — |
| T-SEC-01 | Sin token | 401 | — |
| T-SEC-02 | Token con firma inválida o manipulado | 401 | `AUTHZ_DENIED` |
| T-SEC-03 | Token expirado | 401 | — |
| T-SEC-04 | Sesión expirada por inactividad (> 15 min) | 401 + sesión cerrada `INACTIVIDAD` | `AUTH_SESSION_EXPIRED` |
| T-SEC-05 | Token de una sesión reemplazada por un login nuevo | 401 | `AUTHZ_DENIED` |
| T-SEC-06 | Token revocado (logout o inhabilitación) | 401 | `AUTHZ_DENIED` |
| T-SEC-07 | Cuenta INACTIVA con token aún no expirado | 401 | `AUTHZ_DENIED` |
| T-SEC-08 | Módulo INACTIVO | 403 | `AUTHZ_DENIED` |
| T-SEC-09 | Módulo no asignado | 403 | `AUTHZ_DENIED` |
| T-SEC-10 | Permiso ausente | 403 | `AUTHZ_DENIED` |
| T-SEC-11 | Permiso INACTIVO / rol INACTIVO / perfil INACTIVO | 403 | `AUTHZ_DENIED` |
| T-SEC-12 | Token restringido "debe cambiar contraseña" sobre otra ruta | 403 | — |
| T-SEC-13 | Fallo de auditoría simulado en una operación FC | 503 y **ningún cambio persistido** | Registro en `ops` al recuperarse |
| T-SEC-14 | Redis no disponible | 503 (fail-closed) | — |
| T-SEC-15 | Usuario funcional intenta modificar su propio perfil, roles o módulos | 403 | `AUTHZ_DENIED` |
| T-SEC-16 | Acciones sobre una solicitud ya resuelta (aprobada o rechazada) | 409 | — |
| T-SEC-17 | Cualquier payload o respuesta con `empresa` | 422 (entrada: `extra="forbid"`) y nunca en la salida | — |
| T-SEC-18 | Los logs y eventos no contienen contraseña, token ni cookie | Búsqueda en la salida capturada = 0 coincidencias | — |

## E.11 Pruebas E2E (Playwright) propuestas

| ID | Flujo |
|---|---|
| T-E2E-01 | Bootstrap → primer login de admin → cambio obligatorio → dashboard |
| T-E2E-02 | Admin crea usuario → solicitud → autoaprobación → el usuario hace login y cambia la contraseña → ve solo sus módulos |
| T-E2E-03 | Usuario sin módulos → mensaje informativo |
| T-E2E-04 | 5 intentos fallidos → bloqueo → espera simulada → desbloqueo |
| T-E2E-05 | Login en el navegador B → la sesión del navegador A queda invalidada |
| T-E2E-06 | Inactividad → aviso → cierre de sesión |
| T-E2E-07 | Inhabilitación aprobada → la sesión activa del usuario se corta en la siguiente petición |
| T-E2E-08 | Exportación de usuarios → archivo sin columna Empresa + evento de auditoría |

---

## Trazabilidad requisito → prueba

Extracto de los requisitos críticos; la matriz completa se mantendrá como `docs/trazabilidad.csv` desde la Fase 1 con los campos de M §24.

| Requisito | Módulo | Caso de uso | Entidad | Endpoint | Permiso | Evento | Pruebas |
|---|---|---|---|---|---|---|---|
| REQ-AUTH-07 | auth | CU-AUTH-01 | Credencial | POST /auth/login | Público | AUTH_LOCKOUT | T-AUTH-05..08, T-E2E-04 |
| REQ-AUTH-08 | auth/kernel | CU-AUTH-01 | Sesion (+Redis) | todos | — | AUTH_SESSION_EXPIRED | T-SEC-04, T-E2E-06 |
| REQ-AUTH-09 | auth | CU-AUTH-01 | Sesion | POST /auth/login | Público | AUTH_SESSION_REPLACED | T-AUTH-10, T-SEC-05, T-E2E-05 |
| REQ-AUTH-10 | auth/users | CU-APR-02 | Sesion, RefreshToken | POST /requests/{id}/approve | ADM.SOLICITUD.APROBACION | USR_DEACTIVATED | T-SEC-06,07, T-E2E-07 |
| REQ-AUTH-13 | auth | CU-AUTH-08 (CLI) | Usuario, Credencial, Perfil | CLI `bootstrap-admins` | Shell del host | AUTH_BOOTSTRAP | T-AUTH-31..34 |
| REQ-IAM-05 | kernel | todos | vista permisos efectivos | todos | — | AUTHZ_DENIED | T-SEC-00..12 |
| REQ-APR-02 | approvals | CU-APR-02 | Solicitud | POST /requests/{id}/approve | ADM.SOLICITUD.APROBACION | APR_APPROVED | T-APR-03,04 |
| REQ-APR-03 | approvals | CU-USR-04 | SolicitudItem | PATCH /admin/users/{id} | ADM.USUARIO.EDICION | APR_REQUEST_CREATED | T-APR-05,06 |
| REQ-AUD-04 | audit | CU-AUD-03 | audit.Evento | GET /admin/audit/verify | ADM.AUDITORIA.CONSULTA | AUD_VERIFIED | T-AUD-05..09 |
| REQ-AUD-07 | kernel | todos los FC | audit.Evento | todos los FC | — | — | T-SEC-13 |
| REQ-USER-03 | todos | — | — (ausente) | todos | — | — | T-SEC-17, T-USR-12,25 |
| REQ-NOT-05 | notifications | CU-NOT-02 | EntregaNotificacion | — (worker) | — | NOT_DELIVERY_FAILED | T-NOT-06..08 |
| REQ-TH-03 | th | CU-TH-01 | Solicitud (origen TH) | POST /admin/th/files | ADM.TH.CREACION | APR_REQUEST_CREATED | T-TH-10 |
