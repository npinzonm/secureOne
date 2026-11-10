# Fase 4 — IAM y autorización por operación

Rama: `feature/fase-4-iam`, creada desde `develop` (que ya incluye las Fases 1–3).

## Alcance
1. **Modelo IAM** (migración 0003): `rol`, `perfil_rol`, `permiso`, `rol_permiso`, `modulo`, `usuario_modulo` y `dominio` (informativo).
   - Todas las asociaciones son históricas: se inhabilitan, nunca se borran.
   - Cada permiso pertenece obligatoriamente a un módulo y tiene una de las 6 categorías aprobadas.
2. **Catálogos organizacionales** `gerencia`, `area` y `cargo`, y sus columnas en `usuario`:
   - **sin datos**: solo se cargarán desde Talento Humano (PD-09);
   - consistencia gerencia ↔ área garantizada por clave foránea compuesta.
3. **Datos iniciales (PROPUESTOS, reversibles):**
   - módulos `ADM` (orden 1) e `IND` (orden 2, solo el contenedor del módulo);
   - catálogo de permisos `ADM.*` (ESP-ADM-IAM §5);
   - rol de sistema `ADMINISTRADOR_TOTAL` con todos los permisos `ADM.*`, asociado al perfil `ADMINISTRADOR` (PD-06 APROBADO);
   - módulo `ADM` asignado a los administradores, tanto a los existentes como a los que cree el bootstrap.
4. **Permisos efectivos:** vista `app.v_permiso_efectivo`. Solo cuentan usuario, perfil, rol, permiso y módulo **activos** y el **módulo asignado**, sin duplicados (REQ-IAM-04).
5. **Guarda `require("MOD.RECURSO.CATEGORIA")`** con las 7 validaciones de REQ-IAM-05:
   - token, sesión, inactividad y cuenta (ya en la Fase 3);
   - **estado del módulo, asignación del módulo y permiso efectivo** (nuevas);
   - en `ADM`, además, el perfil `ADMINISTRADOR` (PD-06);
   - cada denegación se audita como `AUTHZ_DENIED` (fail-closed).
6. **Endpoints de consulta** (no requieren matriz de aprobación):
   - `/me/modules` (módulos asignados y activos, en el orden global; mensaje si no hay ninguno) y `/me/permissions`;
   - `/admin/users` (consulta central con filtros, sin Empresa), `/admin/users/{id}` y `/admin/users/{id}/activity` (estas dos auditadas como consultas sensibles, PD-24 PROPUESTO);
   - `/admin/profiles`, `/admin/roles`, `/admin/permissions`, `/admin/modules`, `/admin/domains` y `/admin/org/*`.
7. **Batería negativa genérica T-SEC** aplicada a **todas** las rutas protegidas, más la meta-prueba T-SEC-00: ninguna ruta queda sin guarda.

## Fuera de alcance → Fase 5 (bloqueado por PD-05)
**Toda operación administrativa que modifica datos:**
- alta, edición, inhabilitación y reactivación de usuarios;
- asignación de módulos;
- CRUD de perfiles, roles, permisos, módulos y dominios;
- orden de módulos, reset de contraseña y revocación de sesión.

La matriz «directa / con aprobación» (PD-05) decide cómo se implementa cada una, y sigue PENDIENTE.

## Requisitos cubiertos
REQ-IAM-01..07, 10, 12, 14, 16 (base) · REQ-USER-02, 06 (modelo), 09, 10 · REQ-AUTH-16 (consulta) · REQ-AUD-06 (consultas sensibles) · REQ-USER-03.

## Criterios de aceptación
1. Los permisos efectivos excluyen permiso, rol, perfil o módulo inactivos y los módulos no asignados; un permiso que llega por dos roles aparece una sola vez.
2. Toda ruta protegida responde 401 sin token, con token inválido, expirado, de una sesión reemplazada, revocada o de una cuenta inactiva.
3. Responde 403 con módulo inactivo, módulo no asignado, permiso ausente o inactivo, rol inactivo, perfil inactivo y token restringido. En `ADM`, también si el perfil no es `ADMINISTRADOR` aunque tenga el permiso.
4. Cada denegación por autorización genera `AUTHZ_DENIED` con el motivo.
5. T-SEC-00: todas las rutas no públicas declaran una guarda.
6. `/me/modules` devuelve solo módulos asignados y activos, en el orden global; con 0 módulos, lista vacía y mensaje informativo (el usuario se autentica igual).
7. `/admin/users` filtra por los campos aprobados; ni la API ni el esquema OpenAPI contienen «empresa».
8. La consulta de la ficha y de la actividad de un usuario se audita; los listados no.
9. Un usuario funcional no puede ver la ficha de otro (403).

## Resultado (ejecutado el 2026-11-10)

| # | Criterio | Resultado |
|---|---|---|
| 1 | Permisos efectivos | OK: se excluyen permiso, rol, asociación perfil-rol, perfil, módulo o usuario inactivos; un permiso que llega por dos roles aparece una vez; el prefijo del permiso debe ser su módulo y la categoría su sufijo (BD) |
| 2 | Batería 401 sobre **todas** las rutas `/admin` | OK: sin token, token inválido, expirado, sesión reemplazada, sesión revocada, cuenta inactiva |
| 3 | Batería 403 | OK: módulo inactivo, módulo no asignado, permiso individual inactivo (afecta solo a sus rutas), rol inactivo, perfil inactivo, usuario sin permiso, perfil no ADMINISTRADOR con permiso (PD-06), token restringido |
| 4 | `AUTHZ_DENIED` con motivo | OK; la denegación es fail-closed (auditoría caída → 503) |
| 5 | T-SEC-00 | OK: la meta-prueba recorre todas las rutas registradas; las de `/admin` solo usan permisos `ADM.*` |
| 6 | `/me/modules` | OK: orden global; un módulo inactivo desaparece; con 0 módulos, lista vacía + mensaje |
| 7 | Filtros sin Empresa | OK; los comodines del usuario se tratan como texto; el OpenAPI no contiene «empresa» |
| 8 | Auditoría de consultas | OK: ficha (`USR_VIEWED`) y actividad (`USR_ACTIVITY_VIEWED`) auditadas; los listados no |
| 9 | Ficha de otro usuario | OK: 403 para un usuario funcional |

- **Pruebas:** `ruff` sin hallazgos; 53 unitarias/API; 48 de integración (15 de la Fase 2 + 18 de la 3 + 15 de la 4).
- **Stack base:** migración `0002 → 0003` aplicada; 2 módulos, 38 permisos `ADM.*` y rol `ADMINISTRADOR_TOTAL` con los 38; `/admin/*` sin token → 401; cadena de auditoría íntegra.
- **CI de GitHub:** la Fase 3 (PR y `develop`) terminó en *success*.

**Pendiente:**
- Las operaciones que modifican datos de administración pasan a la Fase 5, **bloqueada por PD-05**.
- Los catálogos organizacionales existen pero están vacíos hasta la integración TH (PD-09).
- En el stack base sigue sin haber administradores (`make bootstrap-admin`).
