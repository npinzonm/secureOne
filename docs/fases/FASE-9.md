# Fase 9 — Frontend funcional (DD-07)

**Especificación UX: DEFINIDA POR DELEGACIÓN** ([DD-07](../06-definiciones-delegadas.md#dd-07--pd-22-experiencia-de-usuario-v10)): pantallas funcionales y sobrias; no es un diseño visual de marca.

## Alcance implementado
| Área | Pantallas |
|---|---|
| Acceso | Login (mensaje genérico, contraseña no retenida); cambio de contraseña (obligatorio con temporal, reglas visibles; tras cambiarla, nuevo login) |
| Sesión | Token **solo en memoria**; refresh por cookie `HttpOnly` (recupera la sesión tras recargar); renovación proactiva que **no** cuenta como actividad; **aviso 60 s antes** del cierre por inactividad («Seguir conectado» / «Cerrar sesión»); logout |
| Inicio | Dashboard con los módulos asignados y activos en orden global; mensaje si no hay ninguno; Indicium Insight como «Módulo en levantamiento funcional» |
| Notificaciones | Campana con contador (usa `/notifications/count`, que **no extiende la sesión**); bandeja propia con «marcar como leída» |
| Administración | Menú lateral filtrado por permisos efectivos (solo presentación). Pantallas:<br>• **Usuarios:** filtros aprobados, exportación Excel, alta con gerencia → área dependiente y tipo NORMAL/EXCEPCIONAL; ficha con actividad, historial por atributo y de estados, y acciones directas o con aprobación<br>• **Solicitudes:** bandeja y detalle; aprobar (con autoaprobación), rechazar o cancelar con motivo<br>• **Perfiles, Roles, Permisos:** con **impacto previo** antes de confirmar<br>• **Módulos:** orden ↑↓; al reactivar, asignaciones a revisar<br>• **Dominios**<br>• **Talento Humano:** carga, ejecuciones con filas, propuestas versionadas y decisión de alta, alertas<br>• **Auditoría:** consulta, exportación y verificación de integridad<br>• **Errores:** estado de atención<br>• **Entregas de notificaciones**<br>• **Parámetros** |
| Secretos | Las contraseñas temporales se muestran una vez en un diálogo con «Copiar» y advertencia; nunca se guardan |
| Estilo | CSS propio con tokens, claro/oscuro según el sistema, foco visible, responsive hasta 360 px. Sin librerías de UI ni de estado |

Cambio de backend asociado: `GET /api/v1/notifications/count` (`touch=False`). Sin él, la campana mantendría viva la sesión e impediría el cierre por inactividad (REQ-AUTH-08). La meta-prueba T-SEC-00 lo cubre como ruta de solo sesión.

## Verificación (ejecutada el 2026-11-10)
**Estáticas y build:** `tsc` sin errores; `next build` de producción con 21 rutas.

**Navegador real, en el ambiente de pruebas (8081):**
| Flujo | Resultado |
|---|---|
| Login fallido | Mensaje genérico, contraseña limpiada |
| Login válido → dashboard | Solo el módulo asignado; la campana muestra las no leídas |
| Recarga completa de página | La sesión se recupera con la cookie de refresh (`Secure` funciona en `http://127.0.0.1`) |
| Crear perfil | Creado; el perfil de sistema se muestra protegido, sin acciones |
| TH → decidir un nuevo funcionario | Modal precargado con la planta; «Solicitud de alta #2 creada»; la propuesta sale de las abiertas |
| Aprobar la solicitud (autoaprobación) | Diálogo de contraseña temporal de una sola vez |
| Auditoría | «Cadena íntegra: 15 eventos»; la consulta lista la secuencia completa (bootstrap, logins, TH, perfil, solicitud, alta, aprobación, verificación, consulta) |
| Aviso de inactividad | Con el TTL reducido a 70 s: aparece «¿Sigue ahí?» con cuenta regresiva; los sondeos no extendieron la sesión; «Seguir conectado» → TTL 898 s |
| Sondeos | En 42 s: 2 de `/auth/session` y 1 de `/notifications/count` (sin intervalos duplicados) |
| Móvil (375 px) | Tras la corrección, sin desbordamiento horizontal (`scrollWidth` = `clientWidth` = 375) |
| Logout | Una ruta protegida redirige al login; la cookie de refresh ya no restaura la sesión |
| Consola | Solo los 401 esperados (login fallido y refresh sin sesión) |

- **Backend tras el cambio:** `ruff` OK; 65 unitarias/API; 87 de integración.
- **Stack base:** 7 servicios `healthy`; `/`, `/login`, `/administracion/usuarios` y `/cambio-contrasena` → 200.

**Defecto encontrado y corregido:** en móvil la cuadrícula no se encogía (`min-width: auto`) y los formularios desbordaban horizontalmente. Corregido con `min-width: 0` y columnas `minmax(min(220px, 100%), 1fr)`.

## Pendiente
- Pruebas E2E automatizadas de navegador (Playwright) → Fase 10.
- El diseño visual de marca queda pendiente de una especificación UX real (DD-07 es provisional).
- La campana se actualiza cada 60 s (no en tiempo real).
