# ESP-ADM-IAM · Especificación funcional — Perfiles, roles, permisos, módulos y dominios

> **Estado del documento: PROPUESTO.** Las reglas marcadas APROBADO provienen de P/M.

## 1. Objetivo
Administrar el modelo **Usuario → Perfil → Roles → Permisos** (APROBADO, D-IAM-001) y los módulos y dominios, con impacto previo y trazabilidad.

## 2. Casos de uso

| ID | Caso de uso | Aprobación (PD-05) |
|---|---|---|
| CU-IAM-01 | Crear, editar, activar o inactivar un perfil y asignarle roles | Directa |
| CU-IAM-02 | Crear, editar, activar o inactivar un rol | Directa |
| CU-IAM-03 | Asignar o quitar permisos de un rol | Directa, con impacto previo |
| CU-IAM-04 | Crear, editar, activar o inactivar un permiso | Directa, con impacto previo |
| CU-IAM-05 | Crear, editar, activar o inactivar un módulo | Directa |
| CU-IAM-06 | Reordenar módulos | **Directa (APROBADO)** |
| CU-IAM-07 | Gestionar dominios (informativos) | Directa |
| CU-IAM-08 | Asignar o revocar módulos de un usuario | Con aprobación (PROPUESTO) |
| CU-IAM-09 | Calcular permisos efectivos | Interno |
| CU-IAM-10 | Mostrar los módulos del usuario en el dashboard | — |

## 3. Reglas

| # | Regla | Estado |
|---|---|---|
| R1 | Un usuario tiene exactamente 1 perfil; un perfil tiene 0..n roles; un rol tiene 0..n permisos. | APROBADO |
| R2 | No existen permisos directos a usuario. | APROBADO |
| R3 | Permisos efectivos = unión sin duplicados de los permisos ACTIVOS de los roles ACTIVOS del perfil ACTIVO, filtrada por módulos ACTIVOS y asignados. | APROBADO |
| R4 | Todo permiso tiene un módulo y una categoría ∈ {Consulta, Creación, Edición, Eliminación, Aprobación, Exportación}. "Eliminación" significa **inhabilitación lógica**. | APROBADO / PROPUESTO (interpretación) |
| R5 | Un perfil con usuarios ACTIVOS no se inactiva: se responde 409 con la lista de usuarios a reasignar. | APROBADO |
| R6 | Los cambios en roles o permisos devuelven primero un **impacto** (perfiles y usuarios afectados) con un `confirm_impact_token` de un solo uso. La confirmación lo exige; si el impacto cambió entre medias, se responde 409. | APROBADO (impacto) / PROPUESTO (mecanismo) |
| R7 | Inactivar un módulo revoca el acceso de inmediato (la autorización lo comprueba en cada petición). Al reactivarlo, se devuelve la lista de asignaciones históricas para que el admin confirme cuáles reactiva; por defecto quedan como estaban. | APROBADO / PROPUESTO (por defecto) |
| R8 | El orden de los módulos es global; reordenar es una operación directa auditada. | APROBADO |
| R9 | Los dominios no participan en la autorización. | APROBADO |
| R10 | Las asociaciones (PerfilRol, RolPermiso, UsuarioModulo) se inhabilitan, nunca se borran. | APROBADO (regla 11) |
| R11 | El perfil ADMINISTRADOR y su rol son de sistema: no se renombran, no se inactivan y no pierden permisos `ADM.*`. | PROPUESTO (PD-06) |
| R12 | Los permisos de sistema (los del catálogo) no se pueden borrar ni cambiar de código; solo describir o inactivar, salvo los del rol ADMINISTRADOR. | PROPUESTO |
| R13 | Un usuario funcional no puede ejecutar ninguna operación IAM sobre sí mismo ni sobre otros sin el permiso correspondiente. | APROBADO |

## 4. Módulos iniciales (PROPUESTO)

| Código | Nombre | Orden | Estado inicial |
|---|---|---|---|
| `ADM` | Administración | 1 | ACTIVO |
| `IND` | Indicium Insight | 2 | ACTIVO (shell) |

## 5. Catálogo de permisos (PROPUESTO)

Formato `MÓDULO.RECURSO.CATEGORÍA`. Todos pertenecen a `ADM` y forman el rol de sistema `ADMINISTRADOR_TOTAL` del perfil `ADMINISTRADOR`.

| Recurso | CONSULTA | CREACION | EDICION | ELIMINACION (inhab.) | APROBACION | EXPORTACION |
|---|---|---|---|---|---|---|
| USUARIO | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| PERFIL | ✓ | ✓ | ✓ | ✓ | — | — |
| ROL | ✓ | ✓ | ✓ | ✓ | — | — |
| PERMISO | ✓ | ✓ | ✓ | ✓ | — | — |
| MODULO | ✓ | ✓ | ✓ | ✓ | — | — |
| DOMINIO | ✓ | ✓ | ✓ | ✓ | — | — |
| SOLICITUD | ✓ | ✓ | — | — | ✓ | — |
| AUDITORIA | ✓ | — | — | — | — | ✓ |
| ERROR | ✓ | — | ✓ | — | — | — |
| NOTIFICACION | ✓ | — | — | — | — | — |
| TH | ✓ | ✓ | — | — | — | — |
| PARAMETRO | ✓ | — | ✓ | — | — | — |
| ORG | ✓ | — | — | — | — | — |

Indicium Insight (`IND.*`): **no se crean permisos** hasta el levantamiento (REQ-IND-02). Solo existe la asignación del módulo.

## 6. Perfiles iniciales (PROPUESTO)

| Perfil | Roles | Nota |
|---|---|---|
| ADMINISTRADOR (sistema) | ADMINISTRADOR_TOTAL | Máx. 2 usuarios (PD-06) |
| Responsable, Visualizador | — | Mencionados como **ejemplos** en M §9.1. **No se crean** hasta que se definan sus permisos (dependen de Indicium). |

## 7. Criterios de aceptación
1. Quitar un permiso de un rol sin el token de impacto → 422. Con un token de impacto obsoleto → 409.
2. Inactivar un perfil con 1 usuario activo → 409 con la lista de usuarios.
3. Un usuario con módulo `IND` asignado pero inactivo no lo ve en `/me/modules` y recibe 403 en sus rutas.
4. Un rol con un permiso duplicado por dos vías aparece una sola vez en los permisos efectivos.
