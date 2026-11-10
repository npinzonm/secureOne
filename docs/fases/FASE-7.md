# Fase 7 — Auditoría consultable, registro de errores, notificaciones y worker

Rama: `feature/fase-7-auditoria-notificaciones`, creada desde `feature/fase-6-solicitudes` (Fase 6 aún sin fusionar).

## Alcance

### A. Auditoría (REQ-AUD-04, 06; D-AUD-001)
| Endpoint | Permiso | Evento |
|---|---|---|
| `GET /admin/audit/events` (filtros: fechas, actor, categoría, acción, módulo, entidad, resultado, correlación) | `ADM.AUDITORIA.CONSULTA` | `AUD_QUERIED` |
| `POST /admin/audit/events/export` (.xlsx) | `ADM.AUDITORIA.EXPORTACION` | `AUD_EXPORTED` |
| `GET /admin/audit/verify` | `ADM.AUDITORIA.CONSULTA` | `AUD_VERIFIED` |

Sin endpoints de edición ni de borrado: la inmutabilidad la garantiza la BD (Fase 2).

### B. Exportación de usuarios (REQ-USER-11)
`POST /admin/users/export` (.xlsx con los mismos filtros de la consulta central, **sin Empresa**), con permiso `ADM.USUARIO.EXPORTACION` y evento `USR_EXPORTED`.

### C. Registro de errores (REQ-ERR-01/02)
- `GET /admin/errors` (filtros) con permiso `ADM.ERROR.CONSULTA`.
- `PATCH /admin/errors/{id}` (estado de atención; operación directa) con permiso `ADM.ERROR.EDICION` y evento `ERR_STATUS_CHANGED`.
- Sin borrado.

### D. Notificaciones (REQ-NOT-01..07, REQ-APR-08)
- **Generación** dentro de la transacción de la operación (patrón *outbox*), en un *savepoint*. Si la generación falla, **la operación aprobada y auditada no se revierte** (D-NOT-001): se registra el error.
- **Destinatarios obligatorios:** todos los usuarios activos con perfil `ADMINISTRADOR`. Se calculan en el servidor y no hay forma de editarlos.
- **Canales:** `BANDEJA` y `CORREO`, con una entrega independiente por canal y destinatario.
- **Eventos de esta fase:**
  - solicitud creada, aprobada, rechazada o cancelada;
  - incidente de auditoría registrado;
  - entrega agotada (alerta técnica, **solo bandeja**).
  - Los eventos TH llegan en la Fase 8.
- **Bandeja propia:** `GET /notifications` y `POST /notifications/{id}/read` (solo las propias).
- **Seguimiento:** `GET /admin/notifications/deliveries` con permiso `ADM.NOTIFICACION.CONSULTA`.
- **Contenido** sin secretos ni datos sensibles: número y tipo de solicitud, usuario de red objetivo, resultado. Nunca contraseñas.

### E. Worker (`app.worker`, contenedor propio)
- Procesa las entregas pendientes con `FOR UPDATE SKIP LOCKED`.
- Reintentos con backoff de **1, 5, 15 y 60 min** (PD-11, PROPUESTO). Al agotarlos: estado `AGOTADA`, alerta técnica en la bandeja y `ops.registro_error` (categoría NOTIFICACION).
- Vuelca periódicamente el *spool* de incidentes de auditoría (pendiente desde la Fase 2).
- **Cierra en BD las sesiones abandonadas** (pendiente desde la Fase 3): sesiones abiertas cuya clave de Redis expiró → `INACTIVIDAD`, auditado.
- *Heartbeat* para el health check.

### F. Correo
- SMTP configurable por variables de entorno.
- **Mailpit** como servidor SMTP local (UI en `127.0.0.1:8025`). v1.0 no tiene integraciones corporativas obligatorias (M §7.1).
- La dirección de cada administrador es el campo `correo` de su usuario (PROPUESTO, pregunta abierta de PD-11).

## Decisiones aplicadas
- **APROBADAS:** D-AUD-001/002, D-NOT-001, REQ-NOT-02/03/05/06.
- **PROPUESTAS:**
  - backoff 1/5/15/60 min y 4 intentos;
  - catálogo de eventos (ESP-NOT §2);
  - consultas sensibles auditadas (PD-24);
  - **tope de 50 000 filas por exportación**: si se alcanza, la respuesta lo indica con la cabecera `X-Export-Truncated`;
  - neutralización de fórmulas en Excel (celdas que empiezan por `= + - @`).

## Criterios de aceptación
1. Consultar, exportar y verificar la auditoría queda auditado. El Excel contiene los eventos filtrados y neutraliza las fórmulas.
2. La exportación de usuarios es un .xlsx sin columna Empresa y queda auditada.
3. Se puede cambiar el estado de atención de un error (auditado); no hay borrado.
4. Crear o resolver una solicitud genera **una notificación y una entrega por canal para cada administrador activo**. La generación ocurre en la transacción de la operación.
5. Si falla la generación de notificaciones, la operación aprobada se aplica igual y el fallo queda registrado.
6. El worker entrega por bandeja y por correo (comprobado en Mailpit). Con el SMTP caído, la bandeja se entrega igual, el correo se reintenta y, al agotarse, pasa a `AGOTADA` con alerta técnica y registro de error.
7. Cada usuario ve y marca solo sus propias notificaciones.
8. Un incidente de auditoría pendiente se vuelca y notifica sin reiniciar el backend.
9. Las sesiones abandonadas se cierran como `INACTIVIDAD` y quedan auditadas.
10. El worker corre como contenedor con health check; las rutas nuevas quedan cubiertas por T-SEC-00 y por la batería negativa.

## Resultado (ejecutado el 2026-11-10)

| # | Criterio | Resultado |
|---|---|---|
| 1 | Auditoría | OK: consulta por correlación, exportación .xlsx (fórmula `=HYPERLINK(...)` neutralizada como texto) y verificación (íntegra), las tres auditadas en orden (`AUD_QUERIED`, `AUD_EXPORTED`, `AUD_VERIFIED`); PUT/PATCH/DELETE → 405; filtro `empresa` → 422 |
| 2 | Exportación de usuarios | OK: .xlsx sin columna Empresa; `USR_EXPORTED` con filtros y número de filas; usuario funcional → 403 |
| 3 | Errores | OK: listado y cambio de estado de atención (auditado con antes/después); repetir el mismo estado → 422; DELETE → 405 |
| 4 | Generación | OK: crear o aprobar una solicitud genera 4 entregas (2 administradores × bandeja/correo) |
| 5 | D-NOT-001 | OK: con la inserción de notificaciones revocada, la aprobación se aplica (200) y queda `GENERATION_FAILED` en el registro de errores |
| 6 | Entrega y reintentos | OK: Mailpit recibe los correos de ambos administradores; con el SMTP caído, la bandeja se entrega igual y el correo se reintenta (1.er reintento a ~60 s) hasta `AGOTADA` (4 intentos); alerta técnica **solo por bandeja** y `DELIVERY_EXHAUSTED` en el registro de errores; la solicitud de origen no cambia |
| 7 | Bandeja propia | OK: lectura y marca solo de las propias (las ajenas → 404); un usuario funcional no ve notificaciones administrativas |
| 8 | Spool | OK: el incidente se vuelca a `ops` y genera `OPS_AUDIT_OUTAGE` |
| 9 | Sesiones abandonadas | OK: cerradas como `INACTIVIDAD`, auditadas con origen `worker` |
| 10 | Worker en contenedor | OK: **E2E real** en el ambiente de pruebas: una entrega encolada pasó a ENVIADA por bandeja y correo en ~4 s, sin intervención, y llegó a Mailpit; health check `rc=0` |

- **Pruebas:** `ruff` sin hallazgos; 58 unitarias/API; 81 de integración (Fases 2–7).
- **Stack base:** migración `0005 → 0006`; 7 servicios `healthy` (nuevos: `worker` y `mailpit`, UI en 127.0.0.1:8025); `/admin/audit/*` sin token → 401; cadena íntegra; 0 secretos en logs.

**Defecto encontrado y corregido:** la meta-prueba detectó que el OpenAPI contenía la palabra «empresa» en dos docstrings («sin Empresa»). Se reescribieron para que el término no aparezca en ninguna salida de la API.

**Pendiente:**
- Notificaciones de eventos TH (Fase 8).
- La dirección de correo de los administradores es el campo `correo` del usuario (PROPUESTO; pregunta abierta de PD-11).
- No hay proveedor SMTP corporativo: Mailpit es el SMTP del prototipo.
