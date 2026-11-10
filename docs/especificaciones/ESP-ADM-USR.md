# ESP-ADM-USR · Especificación funcional — Administración de usuarios

> **Estado del documento: PROPUESTO.** Las reglas marcadas APROBADO provienen de P/M.

## 1. Objetivo
Gestionar el ciclo de vida de usuarios internos (alta, modificación, inhabilitación, reactivación, consulta y exportación), con aprobación y trazabilidad completas y **sin el campo Empresa**.

## 2. Atributos del usuario (PROPUESTO; REQ-USER-15 pendiente)

| Campo | Tipo / formato | Obligatorio | Editable | Estado del campo |
|---|---|---|---|---|
| Usuario de red | 8 caracteres alternados letra/número (PD-07); único sin distinguir mayúsculas | Sí | **No** (PROPUESTO) | APROBADO |
| Identificación | Texto alfanumérico, máx. 20, único | Sí | Solo con solicitud | APROBADO (formato PROPUESTO) |
| Nombre | Texto, máx. 100 | Sí | Con solicitud | APROBADO (ER) |
| Primer apellido | Texto, máx. 50 | Sí | Con solicitud | APROBADO (ER) |
| Segundo apellido | Texto, máx. 50 | No | Con solicitud | APROBADO (ER) |
| Correo | Email válido, máx. 150; **no** es identificador de login | Sí | Con solicitud | APROBADO |
| Gerencia | Catálogo TH activo | Sí | Con solicitud | APROBADO |
| Área | Catálogo TH activo, filtrado por la gerencia | Sí | Con solicitud | APROBADO |
| Cargo / Código de cargo | Catálogo TH activo; código numérico | Sí (internos) | Con solicitud | APROBADO |
| Perfil | Perfil activo, exactamente 1 | Sí | Con solicitud | APROBADO |
| Módulos | 0..n módulos activos | No | Con solicitud | APROBADO |
| Tipo de alta | NORMAL / EXCEPCIONAL | Sí | No | APROBADO (significado: PD-08) |
| Estado | PENDIENTE_ALTA / ACTIVO / INACTIVO | Sistema | Solo con solicitud | PROPUESTO (`PENDIENTE_ALTA`) |
| ~~Empresa~~ | **Eliminado** | — | — | APROBADO (D-TH-002) |

## 3. Casos de uso

| ID | Caso de uso | Aprobación | Notas |
|---|---|---|---|
| CU-USR-01 | Consultar usuarios con filtros (nombre/apellido, usuario de red, identificación, correo, gerencia, área, cargo, estado, tipo) | — | Paginado. Sin filtro Empresa. |
| CU-USR-02 | Ver ficha | — | Auditado como consulta sensible (PD-24). |
| CU-USR-03 | Alta individual | Sí | Crea el Usuario en `PENDIENTE_ALTA` + una Solicitud. Al aprobarse: `ACTIVO`, temporal generada y mostrada al aprobador, `debe_cambiar=true`. |
| CU-USR-04 | Modificar (cambios agrupados) | Sí | Un ítem por atributo; aplicación todo o nada. |
| CU-USR-05 | Inhabilitar (motivo obligatorio) | Sí | Al aplicarse: `INACTIVO`, sesiones y tokens revocados y un registro en el historial. |
| CU-USR-06 | Reactivar | Sí | Al aplicarse: `ACTIVO`, nueva temporal y cambio obligatorio. |
| CU-USR-07 | Exportar a Excel lo filtrado | — | `.xlsx` sin Empresa; auditado con filtros y número de filas. |
| CU-USR-08 | Consultar la información propia | — | Campos según PD-25. |

## 4. Reglas

| # | Regla | Estado |
|---|---|---|
| R1 | Usuario de red e identificación únicos, incluyendo usuarios INACTIVOS y PENDIENTE_ALTA: un identificador no se reutiliza (PROPUESTO). | APROBADO / PROPUESTO |
| R2 | El área elegida debe pertenecer a la gerencia elegida. | APROBADO |
| R3 | No se puede asignar un catálogo, perfil o módulo INACTIVO. | PROPUESTO |
| R4 | Mientras exista una solicitud PENDIENTE sobre un usuario, no se crea otra sobre él; se cancela la existente o se espera. | PROPUESTO |
| R5 | El alta queda `PENDIENTE_ALTA`: no puede autenticarse y aparece en las consultas con ese estado. Si se rechaza o cancela, el registro pasa a `INACTIVO` con motivo, se conserva y su usuario de red queda reservado. | PROPUESTO (APROBADO: "no efectiva hasta aprobarse") |
| R6 | El perfil ADMINISTRADOR solo puede tenerlo un máximo de 2 usuarios ACTIVOS. | APROBADO (D-ADMIN-001) |
| R7 | Un usuario funcional nunca accede a fichas ajenas (403), aunque conozca el id. | APROBADO |
| R8 | Ningún DTO de entrada acepta campos desconocidos (`extra="forbid"`), así que `empresa` se rechaza. | PROPUESTO |
| R9 | Un administrador no puede inhabilitarse a sí mismo si dejaría 0 administradores activos. | PROPUESTO |

## 5. Criterios de aceptación
1. Un alta no aprobada no puede iniciar sesión.
2. Una solicitud con 3 cambios aplica los 3 o ninguno, y el historial muestra 3 cambios de atributo.
3. La exportación no contiene una columna Empresa y genera `USR_EXPORTED`.
4. Al aprobarse la inhabilitación, la sesión abierta del usuario recibe 401 en la petición siguiente.
