# Fase 5 — Operaciones administrativas (matriz PD-05 APROBADA)

Rama: `feature/fase-5-administracion`, creada desde `feature/fase-4-iam`. La Fase 4 aún no está fusionada en `develop`.

## Alcance

### A. Operaciones **directas** (se aplican de inmediato, auditadas y fail-closed)
| Operación | Endpoint | Regla clave |
|---|---|---|
| Contraseña temporal | `POST /admin/users/{id}/password-reset` | Solo cuentas ACTIVAS; la temporal se muestra **una vez** al administrador; `debe_cambiar`; la sesión se revoca; no se registra la contraseña |
| Revocar la sesión de un usuario | `POST /admin/users/{id}/sessions/revoke` | `REVOCADA_ADMIN` |
| Perfiles | `POST/PATCH /admin/profiles`, `POST /admin/profiles/{id}/status` | No se inactiva un perfil con usuarios activos (409); el perfil de sistema no se modifica |
| Roles y sus permisos | `POST/PATCH /admin/roles`, `POST .../permissions/impact`, `PUT .../permissions`, `POST .../status` | **Impacto previo obligatorio** (token de confirmación de un solo contexto); el rol de sistema no se modifica |
| Permisos | `POST/PATCH /admin/permissions`, `POST .../status/impact`, `POST .../status` | Módulo derivado del prefijo; **impacto previo** al inactivar (PD-16); los permisos de sistema no se inactivan |
| Módulos | `POST/PATCH /admin/modules`, `POST .../status`, `PUT /admin/modules/order` | Inactivar revoca el acceso; reactivar devuelve las asignaciones históricas para revisión; `ADM` no se inactiva |
| Dominios (informativos) | `POST/PATCH /admin/domains`, `POST .../status` | — |
| Parámetros | `GET/PATCH /admin/parameters` | Inicial: `th.umbral_alerta_horas = 4` (D-TH-003) |

### B. Operaciones **con aprobación** (en esta fase solo se crea la solicitud; no se aplica nada)
| Operación | Endpoint | Tipo de solicitud |
|---|---|---|
| Alta de usuario | `POST /admin/users` | `ALTA_USUARIO`: el usuario queda `PENDIENTE_ALTA`, sin credencial y sin poder autenticarse |
| Modificar datos o perfil (cambios agrupados) | `PATCH /admin/users/{id}` | `MODIFICACION_USUARIO`: un ítem por atributo modificado |
| Asignar o revocar módulos | `PUT /admin/users/{id}/modules` | `MODULOS_USUARIO` |
| Inhabilitación manual | `POST /admin/users/{id}/deactivate` | `INHABILITACION_USUARIO` (motivo obligatorio) |
| Reactivación | `POST /admin/users/{id}/reactivate` | `REACTIVACION_USUARIO` (motivo obligatorio) |
| Consulta de solicitudes | `GET /admin/requests`, `GET /admin/requests/{id}` | — |

**Aprobar, rechazar, cancelar y aplicar** son la **Fase 6**.

## Reglas aplicadas
**APROBADAS:**
- REQ-USER-01/04/05/06/07/08;
- REQ-IAM-08/09/11/13;
- REQ-APR-01/03/04/06 (inmutabilidad);
- D-ADMIN-001;
- **sin Empresa**.

**PROPUESTAS:**
- una sola solicitud PENDIENTE por usuario (ESP-ADM-USR R4, garantizada en BD);
- el usuario de red no se edita;
- un administrador no puede dejar al sistema sin administradores activos (R9);
- objetos de sistema protegidos (R11/R12);
- motivo mínimo de 10 caracteres;
- el token de impacto vence a los 10 min.

**Gerencia, área y cargo son obligatorios en el alta** (P §6.1: «código de cargo obligatorio para usuarios internos»). Como esos catálogos solo se cargan desde TH, **en el stack real el alta seguirá sin poder completarse hasta la Fase 8**. Las pruebas cargan los catálogos directamente en la BD de pruebas.

## Fuera de alcance
- Aprobación y aplicación de solicitudes (Fase 6).
- Notificaciones a los administradores al crear una solicitud (Fase 7; queda pendiente REQ-APR-08).
- Registro de errores por la API (Fase 7).

## Criterios de aceptación
1. Toda operación directa modifica los datos y registra su evento con antes/después en la misma transacción. Si la auditoría falla → 503 y nada cambia.
2. Contraseña temporal: la respuesta la contiene una sola vez; ni la BD ni la auditoría ni los logs la contienen en claro; el usuario debe cambiarla y su sesión anterior queda revocada.
3. Inactivar un perfil con usuarios activos → 409 con los usuarios afectados.
4. Cambiar los permisos de un rol o inactivar un permiso sin token de impacto → 422; con un token obsoleto (el impacto cambió) o de otra operación → 409.
5. El perfil `ADMINISTRADOR`, el rol `ADMINISTRADOR_TOTAL`, los permisos de sistema y el módulo `ADM` están protegidos (409).
6. Reordenar módulos exige una permutación completa y es directo.
7. Una solicitud creada no modifica la entidad (salvo el registro `PENDIENTE_ALTA` del alta). Guarda un ítem por atributo con valor anterior y nuevo. No se edita (la BD lo impide). No puede haber dos solicitudes pendientes sobre el mismo usuario (409).
8. Validaciones del alta: usuario de red y identificación únicos, área perteneciente a la gerencia, catálogos/perfil/módulos activos, campos desconocidos rechazados (incluido `empresa`).
9. Todas las rutas nuevas quedan cubiertas por T-SEC-00 y por la batería negativa.

## Resultado (ejecutado el 2026-11-10)

| # | Criterio | Resultado |
|---|---|---|
| 1 | Directas auditadas con antes/después; fail-closed | OK: auditoría caída → 503 y el perfil no se crea |
| 2 | Contraseña temporal | OK: se muestra una vez (`Cache-Control: no-store`); en BD solo el hash; ausente en auditoría y logs; `debe_cambiar`; sesión anterior revocada; desbloquea la cuenta; rechazada sobre cuentas inactivas y sobre la propia |
| 3 | Perfil con usuarios activos | OK: 409 con la lista; la inactivación es lógica |
| 4 | Impacto previo (roles, permisos, perfiles) | OK: sin token 422; impacto cambiado 409; token de otro cambio 409; las asociaciones quitadas quedan INACTIVAS (historia) |
| 5 | Objetos de sistema | OK: perfil ADMINISTRADOR, rol ADMINISTRADOR_TOTAL, permisos `ADM.*` (solo se pueden describir) y módulo ADM protegidos |
| 6 | Orden de módulos | OK: permutación completa obligatoria; `/admin/modules` refleja el nuevo orden |
| 7 | Solicitudes | OK: la entidad no cambia (el alta queda `PENDIENTE_ALTA`, sin credencial ni módulos, y no puede autenticarse); ítems solo de los atributos que cambian, con valor anterior; inmutables en BD (UPDATE bloqueado por trigger, DELETE sin privilegio); una pendiente por usuario (API 409 + índice único) |
| 8 | Validaciones del alta | OK: duplicados, área de otra gerencia, cargo inactivo, org faltante, módulo inexistente, usuario de red inválido y `empresa` rechazados |
| 9 | T-SEC | OK: T-SEC-00 cubre las nuevas rutas; la batería 401/403 se amplió a **todos los métodos** de `/admin` (≥ 40 combinaciones método-ruta) |

- **Pruebas:** `ruff` sin hallazgos; 53 unitarias/API; 61 de integración (Fases 2–5).
- **Stack base:** migración `0003 → 0004` aplicada; mutaciones sin token → 401; cadena íntegra; 0 secretos en logs.

**Defecto encontrado y corregido:** el cambio de estado genérico (perfiles, roles, permisos, módulos, dominios) respondía 500 porque PostgreSQL no podía inferir el tipo de un parámetro repetido dentro de un `CASE`. Se añadió un `CAST` explícito; lo detectaron las pruebas de integración.

**Pendiente:**
- Aprobación, rechazo, cancelación y aplicación de solicitudes (Fase 6).
- Notificación a los administradores al crear una solicitud (Fase 7, REQ-APR-08).
- En el stack real el alta seguirá rechazándose mientras los catálogos organizacionales estén vacíos (TH, Fase 8).
