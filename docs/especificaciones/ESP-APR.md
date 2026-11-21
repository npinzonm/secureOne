# ESP-APR · Especificación funcional — Solicitudes y aprobaciones

> **Estado del documento: PROPUESTO.** Modelo vigente APROBADO (D-APR-001/002): **una sola aprobación, cualquiera de los dos administradores, autoaprobación permitida.** No se implementa doble aprobación ni la prohibición de autoaprobar.

## 1. Casos de uso

| ID | Caso de uso | Actor |
|---|---|---|
| CU-APR-01 | Consultar solicitudes (bandeja, filtros, detalle con ítems e historial) | Admin |
| CU-APR-02 | Aprobar: aplica todos los ítems en una transacción | Cualquier admin, incluido el solicitante |
| CU-APR-03 | Rechazar con motivo | Cualquier admin |
| CU-APR-04 | Cancelar con motivo y, opcionalmente, crear una solicitud vinculada | Cualquier admin |
| CU-APR-05 | Generar una solicitud desde TH (retiro o alta propuesta) | Sistema |

## 2. Matriz de operaciones (APROBADA 2026-11-10 — PD-05)

| Operación | Tipo | Estado de la clasificación |
|---|---|---|
| Alta de usuario | **Con aprobación** | APROBADO (P §6.1) |
| Inhabilitación por retiro detectado en TH | **Con aprobación** | APROBADO (D-TH-001) |
| Orden de módulos | **Directa** | APROBADO (P §6.2) |
| Modificación de datos de usuario (agrupable) | Con aprobación | APROBADO (PD-05) (P §7 implica que los cambios de usuario se agrupan en solicitudes) |
| Cambio de perfil de un usuario | Con aprobación | APROBADO (PD-05) |
| Asignación o revocación de módulos de un usuario | Con aprobación | APROBADO (PD-05) |
| Inhabilitación manual de usuario | Con aprobación | APROBADO (PD-05) |
| Reactivación de usuario | Con aprobación | APROBADO (PD-05) |
| Generar contraseña temporal / revocar sesión | Directa | APROBADO (PD-05) (urgencia operativa) |
| Gestionar perfiles, roles, permisos y módulos (con impacto previo) | Directa | APROBADO (PD-05) |
| Dominios, parámetros, estado de atención de errores | Directa | APROBADO (PD-05) |
| Carga de archivo TH | Directa (genera solicitudes) | APROBADO (PD-05) |

## 3. Reglas

| # | Regla | Estado |
|---|---|---|
| R1 | Una solicitud se aplica **solo** al aprobarse; antes no hay ningún efecto sobre la entidad objetivo, salvo crear el registro en `PENDIENTE_ALTA` en el caso de alta. | APROBADO |
| R2 | Una aprobación basta. El aprobador puede ser el solicitante. | APROBADO |
| R3 | Solo aprueban los usuarios del perfil ADMINISTRADOR con `ADM.SOLICITUD.APROBACION`. | PROPUESTO (P: «cualquiera de los dos administradores») |
| R4 | Aplicación todo o nada; historial por atributo (`SolicitudItem`). | APROBADO |
| R5 | Rechazo y cancelación exigen motivo (mín. 10 caracteres, PROPUESTO). | APROBADO / PROPUESTO |
| R6 | Una solicitud no se edita nunca; la corrección = cancelar + nueva solicitud vinculada (`solicitud_vinculada_id`). | APROBADO |
| R7 | Solicitudes de TH: si llega una nueva versión de la propuesta, la solicitud anterior pasa a `SUPERADA` y solo la última es aprobable. | APROBADO (versión) / PROPUESTO (estado) |
| R8 | Al aprobar, si el `valor_anterior` de algún ítem ya no coincide con el valor actual, se responde 409 y no se aplica nada. | PROPUESTO |
| R9 | Aprobar, rechazar o cancelar una solicitud ya resuelta → 409 (idempotencia). | PROPUESTO |
| R10 | Cada transición notifica a **ambos** administradores, sin importar quién actuó. | APROBADO |
| R11 | Las solicitudes no expiran. | PROPUESTO (las fuentes no lo indican; no se inventa una caducidad) |

## 4. Estados
`PENDIENTE` → `APROBADA` (aplicada en el mismo commit) | `RECHAZADA` | `CANCELADA` | `SUPERADA`.
Diagrama en [02-arquitectura §C.5](../02-arquitectura.md#c5-ciclo-de-vida-de-una-solicitud-req-apr-).

## 5. Criterios de aceptación
1. Un admin crea y autoaprueba su solicitud: éxito, y el evento registra solicitante = aprobador.
2. No existe en el código ni en la BD ningún estado "esperando segunda aprobación".
3. Rechazar sin motivo → 422.
4. PATCH sobre una solicitud → 405.
5. Si la aplicación falla a mitad, la BD queda como antes y la solicitud sigue `PENDIENTE`.
