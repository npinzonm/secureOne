# A. Matriz de requisitos y estado

> IDs provisionales `REQ-*` (ver [00-README](00-README.md#convenciones)). Fuente: `P §x` = Paquete de transferencia, `M §x` = Documento maestro.
> **Prioridad** (Crítica/Alta/Media/Baja, según M §25) es **PROPUESTA** en todos los casos: las fuentes no la asignan.
> **Fase** = fase de implementación del plan (1–10) en la que se construye.
> La trazabilidad completa requisito → caso de uso → entidad → endpoint → permiso → auditoría → prueba está en [04-api-endpoints.md §Trazabilidad](04-api-endpoints.md#trazabilidad-requisito--prueba).

## 1. Alcance general (GEN)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-GEN-01 | Prototipo funcional ejecutable localmente, sin conexión real con sistemas corporativos. | P §2.2 | APROBADO | Crítica | 1 |
| REQ-GEN-02 | MVP obligatorio: módulos **Administración** e **Indicium Insight**. | P §2.2, PA §2.3 | APROBADO | Crítica | 4–9 |
| REQ-GEN-03 | Componentes del prototipo: Autenticación, Administración, Indicadores, Auditoría, Notificaciones. | M §7 | APROBADO | Crítica | 3–7 |
| REQ-GEN-04 | Arquitectura modular: cada módulo evoluciona sin acoplar sus reglas al resto; se pueden añadir módulos y dominios sin reconstruir el núcleo. | P §2.2, M §3, M §27 | APROBADO | Alta | 2 |
| REQ-GEN-05 | Stack: Next.js, FastAPI, PostgreSQL, Redis, Docker, Compose, Nginx, Git/GitHub, Actions (D-ARCH-001). | P §3 | APROBADO | Crítica | 1 |
| REQ-GEN-06 | Roadmap de módulos (RBA, Certificación de Accesos, Activos, Riesgos, Vulnerabilidades, Terceros, Cumplimiento, Auditoría, Configuración). | P §2.2 | APLAZADO | — | — |
| REQ-GEN-07 | Excluidos del prototipo: gestión documental/evidencias, integraciones corporativas obligatorias, alta disponibilidad/redundancia. | M §7.1, M §22 | EXCLUIDO | — | — |
| REQ-GEN-08 | Capacidades de IA (analítica, recomendaciones) bajo supervisión humana. | M §21 | APLAZADO (fuera del alcance M §7) | — | — |
| REQ-GEN-09 | Gestión de procesos/flujos: no se exige motor general de workflow en el prototipo. | M §14 | APROBADO (restricción) | — | — |
| REQ-GEN-10 | Facilitar la futura migración a Microsoft Azure; evitar dependencias innecesarias del entorno local. | M §16 | APROBADO (principio) | Media | 1 |

## 2. Autenticación y sesiones (AUTH)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-AUTH-01 | Login con **usuario de red** corporativo; el correo es un dato asociado, no el identificador de inicio de sesión. | P §5 | APROBADO | Crítica | 3 |
| REQ-AUTH-02 | Contraseñas almacenadas con hash robusto; nunca en texto plano. | P §11, M §10 | APROBADO (algoritmo: PD-02) | Crítica | 3 |
| REQ-AUTH-03 | Política: mínimo 12 caracteres, con mayúscula, minúscula, número y carácter especial; distinta del usuario de red; no reutilizar las últimas 5. | P §5 | APROBADO | Crítica | 3 |
| REQ-AUTH-04 | Sin vencimiento periódico obligatorio de contraseñas. | P §5 | APROBADO (supera CL regla 10, ver C-10) | Alta | 3 |
| REQ-AUTH-05 | El administrador asigna contraseña temporal; cambio obligatorio en el primer inicio de sesión. | P §5 | APROBADO | Crítica | 3 |
| REQ-AUTH-06 | Recuperación = el administrador genera una nueva contraseña temporal; nunca se muestra ni recupera la anterior. | P §5 | APROBADO | Alta | 3 |
| REQ-AUTH-07 | Al **5.º intento fallido consecutivo**, bloqueo temporal de **15 min** con desbloqueo automático. El bloqueo **no** cambia el estado Activo/Inactivo. | P §5 | APROBADO (supera SQ/CL, ver C-08, C-09) | Crítica | 3 |
| REQ-AUTH-08 | Cierre de sesión tras **15 min consecutivos de inactividad**. | P §5 | APROBADO | Crítica | 3 |
| REQ-AUTH-09 | **Una sesión activa por usuario**; un nuevo login invalida la anterior. | P §5 | APROBADO | Crítica | 3 |
| REQ-AUTH-10 | Inhabilitar una cuenta invalida **inmediatamente** sesiones y tokens e impide nuevos accesos. | P §5, M §9.5 | APROBADO | Crítica | 3–4 |
| REQ-AUTH-11 | Reactivar una cuenta exige contraseña temporal y cambio en el siguiente login. | P §5 | APROBADO | Alta | 4 |
| REQ-AUTH-12 | **Máximo dos administradores**, con los mismos privilegios (D-ADMIN-001). Reemplazo designado por el encargado del área. | P §5, P §14 | APROBADO (supera M §8.1, ver C-01) | Crítica | 3 |
| REQ-AUTH-13 | Bootstrap seguro de los dos administradores al desplegar: contraseña temporal, cambio obligatorio, sin credenciales codificadas ni valores por defecto. | P §5 | APROBADO | Crítica | 3 |
| REQ-AUTH-14 | Autenticación v1.0: usuario/contraseña + **JWT + Refresh Token**. | P §3.1 | APROBADO (estrategia concreta: PD-01) | Crítica | 3 |
| REQ-AUTH-15 | Cierre de sesión voluntario (logout). | M §10 | APROBADO | Alta | 3 |
| REQ-AUTH-16 | Seguimiento de actividad: último ingreso, historial de ingresos, última actividad, intentos fallidos y sesiones activas. | M §11.3 | APROBADO | Alta | 3 |
| REQ-AUTH-17 | La cuenta administrativa es independiente de la cuenta funcional del creador del proyecto; la cuenta funcional no hereda privilegios administrativos. | M §8.2 | APROBADO | Alta | 3 |
| REQ-AUTH-18 | Los desarrolladores no tienen privilegios administrativos permanentes en la aplicación. | M §8.1 | APROBADO | Media | 3 |
| REQ-AUTH-19 | SSO con Microsoft Entra ID (OAuth2/OIDC). | P §3.1 | APLAZADO (Fase 2 del roadmap de autenticación) | — | — |
| REQ-AUTH-20 | MFA (Authenticator/TOTP). | P §3.1 | APLAZADO (Fase 3 del roadmap de autenticación) | — | — |
| REQ-AUTH-21 | Detalle de token/refresh, revocación, almacenamiento de sesión, mensajes y configuración exacta. | P §15 (AUTH) | PENDIENTE → PD-01, PD-17, PD-19 | — | — |

## 3. Usuarios y estructura organizacional (USER)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-USER-01 | Aprovisionamiento **individual y manual** por el administrador; no hay carga masiva por Excel. | P §5 | APROBADO | Crítica | 5 |
| REQ-USER-02 | Datos organizacionales: Gerencia, Área, Cargo, Código de cargo. | P §6.1 | APROBADO | Alta | 4 |
| REQ-USER-03 | **El campo Empresa queda eliminado**: no se almacena, sincroniza, propone, muestra, filtra ni exporta (D-TH-002). | P §6.1, P §14 | APROBADO | Crítica | todas |
| REQ-USER-04 | Usuario de red e identificación son **únicos**. El usuario de red se normaliza (trim, comparación sin distinguir mayúsculas) y sigue el patrón de **8 caracteres alternados letra/número**. | P §6.1 | APROBADO (patrón exacto: PD-07) | Crítica | 4 |
| REQ-USER-05 | Código de cargo numérico obligatorio para usuarios internos. Los usuarios externos quedan fuera de v1.0. | P §6.1 | APROBADO (supera CL, ver C-13) | Alta | 4 |
| REQ-USER-06 | Una gerencia tiene varias áreas y cada área pertenece a una gerencia; al seleccionar la gerencia se filtran sus áreas. | P §6.1 | APROBADO | Alta | 4/9 |
| REQ-USER-07 | El usuario nuevo tiene estado previsto Activo, pero el alta solo se hace efectiva al aprobarse. | P §6.1 | APROBADO | Crítica | 6 |
| REQ-USER-08 | Inhabilitación lógica, nunca borrado físico; se conservan historial, actor, fecha y motivo. | P §6.1, M §9.5 | APROBADO | Crítica | 5 |
| REQ-USER-09 | El usuario funcional consulta su propia información permitida y no puede ver fichas de otros usuarios. | P §6.1 | APROBADO (campos visibles: PD-25) | Alta | 5 |
| REQ-USER-10 | Consulta central con filtros: nombre/apellido, usuario de red, identificación, correo, gerencia, área, cargo, estado y tipo normal/excepcional (sin Empresa). | P §6.1 | APROBADO | Alta | 5 |
| REQ-USER-11 | Exportación a Excel de los resultados filtrados, auditada y sin Empresa. | P §6.1 | APROBADO | Media | 5 |
| REQ-USER-12 | Tipo de alta **normal / excepcional**. | P §6.1, P §8 | APROBADO como atributo; **significado PENDIENTE** (PD-08) | Alta | 5 |
| REQ-USER-13 | Reactivación de usuarios por el administrador. | M §9.5 | APROBADO | Alta | 5 |
| REQ-USER-14 | El usuario inhabilitado no puede iniciar sesión ni acceder a módulos; se conservan sus registros y asignaciones. | M §9.5, P §4 | APROBADO | Crítica | 3–4 |
| REQ-USER-15 | Estructura física final, reglas completas de formularios, atributos y casos excepcionales. | P §15 (USER) | PENDIENTE → atributos PROPUESTOS en [ESP-ADM-USR](especificaciones/ESP-ADM-USR.md) | — | — |

## 4. IAM: perfiles, roles, permisos, módulos (IAM)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-IAM-01 | Jerarquía **Usuario → Perfil → Roles → Permisos**; cada usuario funcional tiene exactamente un perfil (D-IAM-001). | P §4, M §9 | APROBADO (supera ER/CL, ver C-11) | Crítica | 4 |
| REQ-IAM-02 | No se asignan permisos directamente a usuarios. | P §4 | APROBADO | Crítica | 4 |
| REQ-IAM-03 | El usuario funcional no puede autogestionar ni autoasignarse privilegios. | P §4, M §9.2 | APROBADO | Crítica | 4 |
| REQ-IAM-04 | Permisos efectivos = unión, sin duplicados, de los permisos de los roles del perfil. | P §4 | APROBADO | Crítica | 4 |
| REQ-IAM-05 | El backend es la autoridad. En cada operación protegida valida: identidad, cuenta activa, sesión/token, estado del módulo, asignación del módulo, permiso efectivo y reglas de negocio. | P §4.1, M §9.2 | APROBADO | Crítica | 4 |
| REQ-IAM-06 | Cada permiso pertenece a un módulo (obligatorio) y tiene una categoría: Consulta, Creación, Edición, Eliminación, Aprobación o Exportación. | P §6.2 | APROBADO | Crítica | 4 |
| REQ-IAM-07 | Los permisos inactivos no autorizan; las asociaciones históricas pueden conservarse. | P §6.2 | APROBADO | Crítica | 4 |
| REQ-IAM-08 | No se puede inactivar un perfil con usuarios activos sin reasignarlos antes a un perfil activo. | P §6.2 | APROBADO | Alta | 5 |
| REQ-IAM-09 | Los cambios en roles/permisos muestran su impacto (perfiles y usuarios afectados) antes de confirmarse. | P §6.2 | APROBADO | Alta | 5 |
| REQ-IAM-10 | Un usuario puede tener varios módulos; la asignación habilita el acceso pero no concede permisos funcionales. | P §4 | APROBADO | Crítica | 4 |
| REQ-IAM-11 | Los módulos inactivos no son accesibles y su inactivación revoca el acceso; reactivarlos exige revisar las asignaciones históricas. | P §6.2 | APROBADO | Alta | 5 |
| REQ-IAM-12 | El dashboard posterior al login muestra solo los módulos asignados y activos. Un usuario sin módulos puede autenticarse y ve un mensaje informativo. | P §6.2 | APROBADO (supera M §9.3, ver C-02) | Alta | 9 |
| REQ-IAM-13 | El orden de los módulos es uniforme para todos los usuarios; cualquiera de los administradores lo cambia directamente y queda auditado. | P §6.2 | APROBADO | Baja | 5 |
| REQ-IAM-14 | Los dominios son una clasificación conceptual/informativa; no autorizan ni se asignan. | P §4 | APROBADO (supera M §9.3, ver C-03) | Media | 5 |
| REQ-IAM-15 | Los administradores gestionan perfiles, roles, permisos, módulos, dominios y asignaciones. | P §6.2, M §9.2 | APROBADO | Crítica | 5 |
| REQ-IAM-16 | Distinguir responsabilidad de gestión, consulta, modificación y acceso administrativo integral. | M §9.4 | APROBADO (la consulta transversal es PENDIENTE de cada módulo) | Media | 4 |
| REQ-IAM-17 | Catálogo completo de permisos por módulo y contrato de administración. | P §15 (PER/MOD) | PENDIENTE → catálogo PROPUESTO en [ESP-ADM-IAM](especificaciones/ESP-ADM-IAM.md#catálogo-de-permisos-propuesto) | — | — |

## 5. Aprobaciones (APR)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-APR-01 | Las operaciones sujetas a aprobación se registran como solicitudes persistidas y auditables; no se aplican antes de aprobarse. | P §7, P §12 | APROBADO | Crítica | 6 |
| REQ-APR-02 | **Una sola aprobación**; cualquiera de los dos administradores aprueba; **se permite la autoaprobación** (D-APR-001). | P §7 | APROBADO | Crítica | 6 |
| REQ-APR-03 | Los cambios múltiples sobre un usuario se agrupan en una solicitud y se aprueban integralmente (todo o nada), con historial por atributo (D-APR-002). | P §7 | APROBADO | Alta | 6 |
| REQ-APR-04 | Se conservan estados, solicitante, aprobador, fechas, resultado, motivo e historial. | P §7 | APROBADO | Crítica | 6 |
| REQ-APR-05 | Rechazos y cancelaciones requieren motivo. | P §7 | APROBADO | Alta | 6 |
| REQ-APR-06 | Una solicitud enviada no se modifica silenciosamente; si hay un error, se cancela y se crea otra vinculada. | P §7 | APROBADO | Alta | 6 |
| REQ-APR-07 | Las propuestas de TH se versionan bajo un ID estable y solo la última versión es aprobable. | P §7 | APROBADO | Alta | 8 |
| REQ-APR-08 | Ambos administradores reciben las notificaciones definidas, sin importar quién solicita o aprueba. | P §7 | APROBADO | Alta | 7 |
| REQ-APR-09 | No hay doble aprobación ni prohibición de autoaprobación; esta regla no vuelve aprobables las operaciones directas. | P §7 | APROBADO | Crítica | 6 |
| REQ-APR-10 | Matriz final de qué operaciones son directas y cuáles requieren aprobación; estados y notificaciones exhaustivos. | P §15 (APR) | Matriz **APROBADA** (PD-05, 2026-11-10; [ESP-APR §2](especificaciones/ESP-APR.md)); estados y notificaciones exhaustivos: PENDIENTE | Crítica | 5–6 |

## 6. Integración Talento Humano (TH)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-TH-01 | Planta activa: procesamiento diario tras recepción y descifrado autorizado; archivo `.xlsx` (SharePoint previsto). | P §8 | APROBADO (canal de ingreso en el prototipo: PD-10) | Alta | 8 |
| REQ-TH-02 | Planta de retirados: procesamiento semanal y prioritario para detectar retiros. | P §8 | APROBADO | Alta | 8 |
| REQ-TH-03 | Una coincidencia inequívoca por identificación con un usuario activo genera una solicitud de inhabilitación, nunca una inhabilitación automática (D-TH-001). | P §8 | APROBADO | Crítica | 8 |
| REQ-TH-04 | Si se aprueba, se inactiva la cuenta y se invalidan sesiones/tokens; si se rechaza, la cuenta sigue activa y se conserva el motivo. | P §8 | APROBADO | Crítica | 8 |
| REQ-TH-05 | Si un usuario activo deja de aparecer en la planta activa, se genera una alerta a ambos administradores sin cambiar estado ni permisos; una alerta por cada periodo continuo de ausencia. | P §8 | APROBADO | Alta | 8 |
| REQ-TH-06 | Si el archivo diario no llega, se emite una alerta configurable (inicialmente a las 4 h de la hora habitual), sin repetir durante el mismo periodo de ausencia (D-TH-003). | P §8 | APROBADO | Alta | 8 |
| REQ-TH-07 | Se valida estructura, columnas, formato, integridad y duplicados. El procesamiento es parcial; la ejecución se rechaza ante un error estructural. | P §8 | APROBADO | Crítica | 8 |
| REQ-TH-08 | Se conservan resultados, estadísticas, validaciones, errores, propuestas, ejecuciones y reprocesamientos; **el archivo original se elimina tras procesarse** (D-TH-004). | P §8 | APROBADO | Crítica | 8 |
| REQ-TH-09 | Un archivo duplicado no se reprocesa automáticamente. El reproceso exige nueva carga y motivo, y crea una ejecución vinculada a la original. | P §8 | APROBADO | Alta | 8 |
| REQ-TH-10 | Hasta 3 reintentos técnicos (1, 5 y 15 min) sin duplicar operaciones; al agotarlos se registra el error y se notifica. | P §8 | APROBADO | Alta | 8 |
| REQ-TH-11 | Los potenciales funcionarios nuevos no crean cuentas automáticamente; el administrador decide alta normal o excepcional. | P §8 | APROBADO | Alta | 8 |
| REQ-TH-12 | La fuente puede traer Empresa, pero SecureOne la descarta. | P §8 | APROBADO | Crítica | 8 |
| REQ-TH-13 | Los catálogos Gerencias, Áreas, Cargos y Códigos de cargo se sincronizan solo desde TH (sin edición manual); los elementos ausentes se inactivan. | P §6.3 | APROBADO | Alta | 8 |
| REQ-TH-14 | Columnas, formatos, ruta/convención de archivos, reglas de conciliación y cifrado/descifrado. | P §6.3, P §15 (TH) | **PENDIENTE — bloquea la Fase 8** (PD-09) | — | — |

## 7. Auditoría (AUD) y gestión de errores (ERR)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-AUD-01 | Bitácora central de: autenticación, usuarios, IAM/permisos, autorización, aprobaciones/procesos, TH, seguridad, sesiones, consultas sensibles, exportaciones, administración/parámetros, cambios de información y errores relevantes. | P §9.1, M §11.1 | APROBADO | Crítica | 7 (base en 2) |
| REQ-AUD-02 | Campos mínimos: id único, actor, fecha/hora, tipo, módulo, acción, entidad e id afectados, valor anterior/nuevo, resultado, motivo/justificación, IP (si está disponible) y detalle. | P §9.1, M §11.2 | APROBADO | Crítica | 2 |
| REQ-AUD-03 | No se registran contraseñas, tokens, secretos ni credenciales. | P §9.1 | APROBADO | Crítica | 2 |
| REQ-AUD-04 | Inmutable: ningún usuario, ni siquiera el administrador, puede editar o borrar registros. Se recomienda aislar el almacenamiento. | P §9.1, M §11.4 | APROBADO (aislamiento: PD-03) | Crítica | 2 |
| REQ-AUD-05 | Retención indefinida hasta que exista una política formal; revisión anual y posible archivado sin perder trazabilidad. | P §9.1 | APROBADO (supera M §11.4, ver C-06) | Media | 10 |
| REQ-AUD-06 | Se auditan consultas sensibles y exportaciones, no toda búsqueda rutinaria (D-AUD-001); también las consultas y exportaciones de la propia auditoría. | P §9.1, M §11.4 | APROBADO | Alta | 7 |
| REQ-AUD-07 | **Fail-closed**: la operación crítica no se ejecuta sin auditoría garantizada; se informa, se bloquea y se registra un incidente técnico al recuperarse el servicio (D-AUD-002). | P §9.1 | APROBADO (alcance de "crítica": PD-04) | Crítica | 2/7 |
| REQ-AUD-08 | Las modificaciones conservan datos anteriores suficientes para reconstruir el cambio. | M §11.5 | APROBADO | Alta | 5 |
| REQ-AUD-09 | Esquema de eventos, política de integridad/archivo y comportamiento técnico ante indisponibilidad. | P §15 (AUD) | PENDIENTE → PROPUESTO en [ESP-AUD](especificaciones/ESP-AUD.md) (PD-03, PD-04) | — | — |
| REQ-ERR-01 | Registro centralizado de errores técnicos y funcionales, independiente de la auditoría y correlacionado con ella. | M §12 | APROBADO | Alta | 2 |
| REQ-ERR-02 | Categorías: autenticación, validaciones, CRUD, automatizaciones, notificaciones, integraciones, BD, infraestructura, respaldos, recuperación. Campos: id, fecha, módulo, componente, actor/proceso, tipo, severidad, descripción, estado de atención y diagnóstico. | M §12 | APROBADO | Alta | 2 |
| REQ-ERR-03 | Los logs operativos van separados de la auditoría y no contienen secretos. | P §11 | APROBADO | Crítica | 2 |

## 8. Notificaciones (NOT)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-NOT-01 | Canales: bandeja interna y correo corporativo. | P §9.2 | APROBADO | Alta | 7 |
| REQ-NOT-02 | Los dos administradores son destinatarios obligatorios y no se pueden quitar manualmente. | P §9.2 | APROBADO | Alta | 7 |
| REQ-NOT-03 | Generación y entrega independientes: si falla el correo, queda en la bandeja; si falla la bandeja, queda pendiente de publicar. | P §9.2 | APROBADO | Alta | 7 |
| REQ-NOT-04 | Reintentos con estados e intentos registrados; al agotarse, alerta técnica. | P §9.2, M §13.3 | APROBADO (política: PD-11) | Alta | 7 |
| REQ-NOT-05 | Un fallo de notificación no revierte ni bloquea una operación ya aprobada y auditada (D-NOT-001). | P §9.2 | APROBADO | Crítica | 7 |
| REQ-NOT-06 | Las notificaciones no incluyen secretos ni datos sensibles innecesarios. | P §9.2 | APROBADO | Crítica | 7 |
| REQ-NOT-07 | Plantillas reutilizables, destinatarios múltiples, control de duplicados e identificación del evento de origen. | M §13.3 | APROBADO | Media | 7 |
| REQ-NOT-08 | Eventos de indicadores (apertura de periodo, vencimientos…) y modelo híbrido de reglas por KPI. | M §13.1–13.2 | APLAZADO junto con Indicium (ver C-05) | — | — |
| REQ-NOT-09 | Proveedor SMTP, plantillas finales, política de reintentos y catálogo de eventos. | P §15 (NOT) | PENDIENTE → PROPUESTO en [ESP-NOT](especificaciones/ESP-NOT.md) (PD-11) | — | — |

## 9. Indicium Insight (IND)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-IND-01 | Shell del módulo: registro de módulo, navegación y puntos de extensión, sin entidades ni reglas definitivas. | P §10 | APROBADO | Media | 9 |
| REQ-IND-02 | KPI/KGI (14 KGI iniciales), responsables, metas, periodicidad, captura, validación, dashboards, semaforización y reportes. | P §10, M §7 | APLAZADO (D-IND-001) | — | — |
| REQ-IND-03 | Flujo de aprobación de resultados y modificación de históricos. | P §10 | APLAZADO | — | — |

## 10. No funcionales y operación (RNF)

| ID | Requisito | Fuente | Estado | Prior. | Fase |
|---|---|---|---|---|---|
| REQ-RNF-01 | Seguridad por diseño / SSDLC: validación de entradas, protección contra ataques comunes, gestión de dependencias y vulnerabilidades. | M §10, P §11 | APROBADO | Crítica | todas |
| REQ-RNF-02 | Separación frontend / backend / dominio / persistencia. | P §11 | APROBADO | Alta | 2 |
| REQ-RNF-03 | API versionable, validación de entrada/salida y manejo de errores consistente. | P §11 | APROBADO | Alta | 2 |
| REQ-RNF-04 | Migraciones de base de datos versionadas. | P §11 | APROBADO | Crítica | 2 |
| REQ-RNF-05 | Pruebas unitarias, de integración, funcionales, de seguridad, de regresión, de autorización negativa y E2E. | P §11, M §19 | APROBADO | Crítica | todas |
| REQ-RNF-06 | Contenedores reproducibles, configuración por variables de entorno y secretos fuera del repositorio. | P §11 | APROBADO | Crítica | 1 |
| REQ-RNF-07 | Documentación de instalación, configuración, ejecución, migraciones, bootstrap, pruebas y recuperación, en 5 grupos documentales. | P §11, M §23 | APROBADO | Alta | 10 |
| REQ-RNF-08 | Respaldos automáticos diarios y adicionales antes de cambios importantes; restauración probada, registro e integridad. Retención 7 días / 4 semanas / 3 meses, ajustable. | M §15 | APROBADO (ver C-18) | Alta | 10 |
| REQ-RNF-09 | Tres ambientes (desarrollo, pruebas, producción), implementables de forma progresiva. | M §17 | APROBADO | Media | 1 |
| REQ-RNF-10 | Control de versiones con validación de cambios antes de producción. | M §18 | APROBADO | Alta | 1 |
| REQ-RNF-11 | Matriz de trazabilidad obligatoria con los campos de M §24. | M §24 | APROBADO | Alta | todas |
| REQ-RNF-12 | Métricas de rendimiento, disponibilidad, concurrencia, accesibilidad, compatibilidad, RPO/RTO. | P §15 (RNF), M §28 | **PENDIENTE — no se fijan** | — | — |
| REQ-RNF-13 | Diseño UX/UI y navegación final. | P (portada) | PENDIENTE (Fase 9 bloqueada sin especificación; PD-22) | — | — |

---

## Conflictos detectados

Resolución: se aplica la decisión aprobada más reciente (**P**, 04/11/2026). Ningún conflicto se resolvió en silencio.

| ID | Fuente antigua | Fuente vigente | Decisión aplicada |
|---|---|---|---|
| C-01 | M §8.1: **1** administrador | P §5, D-ADMIN-001: máximo **2**, mismos privilegios | 2 administradores |
| C-02 | M §9.3: todo usuario debe tener al menos 1 módulo | P §6.2: un usuario sin módulos puede autenticarse y ve un mensaje | Se permiten 0 módulos |
| C-03 | M §9.3: el usuario recibe dominios dentro de cada módulo | P §4: los dominios son informativos; no autorizan ni se asignan | No hay asignación usuario–dominio |
| C-04 | M §7.1: carga Excel de indicadores excluida | P §10: Indicium incluye «carga masiva» | Sin efecto: Indicium está APLAZADO; se resolverá en su levantamiento |
| C-05 | M §13.1: eventos de notificación de indicadores | P §9.2: notificaciones administrativas a los 2 admins | Administrativas en v1.0; las de indicadores quedan APLAZADAS |
| C-06 | M §11.4: retención de auditoría «se establecerá» | P §9.1: indefinida hasta política formal | Indefinida |
| C-07 | M: sin integración TH | P §6.3, §8: integración TH definida | Dentro del alcance; el contrato de archivos sigue PENDIENTE |
| C-08 | SQ, CL regla 9: bloqueo al **3.er** intento | P §5: al **5.º** intento, 15 min | 5 intentos / 15 min |
| C-09 | SQ, CL: el bloqueo cambia el estado a `BLOQUEADO` | P §5: el bloqueo no cambia Activo/Inactivo | Bloqueo = atributo temporal `locked_until` |
| C-10 | SQ, CL regla 10: la contraseña puede expirar | P §5: sin vencimiento periódico | No hay expiración; solo el cambio obligatorio de la temporal |
| C-11 | ER, CL: `PERFIL_PERMISO` (perfil→permiso directo, sin Rol) | P §4: Perfil → **Roles** → Permisos | Se introduce `Rol`, `PerfilRol` y `RolPermiso` |
| C-12 | ER, CL regla 2: Cargo→Perfil (el cargo determina el perfil) | P §4: el usuario tiene exactamente un perfil, asignado por el administrador | No se adopta Cargo→Perfil (no aprobado); ver PD-15 |
| C-13 | CL: usuarios externos sin cargo | P §6.1: externos fuera de v1.0 | Solo internos; código de cargo obligatorio |
| C-14 | ER: `CARGO` con `gerencia` y `area` como texto | P §6.1/6.3: catálogos Gerencia 1..N Área sincronizados desde TH | Catálogos normalizados `Gerencia`, `Area`, `Cargo` |
| C-15 | CL: `EstadoUsuario = ACTIVO·BLOQUEADO·RETIRADO` | P §5, §8: Activo/Inactivo; el retiro llega como solicitud que inactiva | `ACTIVO` / `INACTIVO` + motivo; también `PENDIENTE_ALTA` (PROPUESTO, REQ-USER-07) |
| C-16 | CL: `AccionAuditoria` incluye `ELIMINAR` | P §11 regla 11: sin borrado físico | No existe una acción de borrado físico sobre entidades conservables |
| C-17 | CL reglas 5–7: inhabilitar perfil/permiso/cargo «si ningún usuario/perfil queda afectado» | P §6.2: perfil → reasignar antes (REQ-IAM-08); permiso → mostrar impacto (REQ-IAM-09); cargo → lo inactiva TH | Se aplican las reglas de P; para permisos ver PD-16 |
| C-18 | M §15.2: retención de respaldos 7d/4s/3m aprobada | P §15: objetivos de respaldo/recuperación pendientes | Se implementa la retención de M (ajustable); RPO/RTO no se fijan |
| C-19 | ER/CL: `AUDITORIA` con 5 campos y FK por `usuario_red` | M §11.2: campos mínimos ampliados | Esquema ampliado (ver D) |
