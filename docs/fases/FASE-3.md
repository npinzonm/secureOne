# Fase 3 — Autenticación y sesiones

Rama: `feature/fase-3-autenticacion`, creada desde `feature/fase-2-fundamentos`. Se rebasará sobre `develop` cuando se fusione el PR de la Fase 2.

## Alcance
1. **Modelo mínimo de identidad** (migración 0002):
   - `perfil`, con el perfil de sistema `ADMINISTRADOR` precargado;
   - `usuario`, `credencial`, `historial_contrasena`, `sesion` y `refresh_token`;
   - máximo 2 administradores activos, garantizado por trigger en la BD.
2. **Bootstrap seguro de administradores** (`app.cli bootstrap-admin`):
   - interactivo, sin valores por defecto;
   - contraseña temporal aleatoria mostrada **una sola vez** en la terminal;
   - rechaza un 3.er administrador.
3. **Login con usuario de red** y hash Argon2id. Mensaje genérico ante cualquier fallo (PD-17).
4. **Política de contraseñas** y cambio obligatorio de la temporal: se emite un token restringido válido solo para cambiar la contraseña y cerrar sesión.
5. **Bloqueo** al 5.º intento fallido consecutivo durante 15 min, con desbloqueo automático y sin cambiar el estado de la cuenta.
6. **Sesiones (PD-01):**
   - access JWT de 5 min con `sid`;
   - sesión viva en Redis con TTL deslizante de 15 min por inactividad;
   - **una sesión por usuario**;
   - refresh opaco que rota en cada uso, con detección de reutilización;
   - Redis caído → 503.
7. Logout, estado de la sesión (`/auth/session`) e información propia (`/me`).
8. **Fail-closed (PD-04)** en todos los eventos de autenticación.
9. **Dependencia de autenticación** reutilizable por todas las rutas protegidas. Verifica las 4 primeras condiciones de REQ-IAM-05: token, sesión, inactividad y cuenta activa. Las de módulo y permiso llegan en la Fase 4.

## Fuera de alcance (y por qué)
- **Endpoints administrativos** (reset de contraseña, revocar sesión, actividad de otro usuario): requieren la autorización por permisos de la Fase 4.
- **Datos organizacionales del usuario** (gerencia, área, cargo): dependen de los catálogos TH (Fases 4 y 8). Los administradores del bootstrap son la *identidad administrativa* de M §8.2 y no llevan datos organizacionales; esto es PROPUESTO.
- **UI:** Fase 9.

## Decisiones aplicadas
- **APROBADAS:** PD-01, PD-04, PD-06, PD-17.
- **PROPUESTAS (reversibles):**
  - PD-02: Argon2id; se guardan las últimas 5 contraseñas.
  - PD-18 (variante): access token en el cuerpo de la respuesta, que el frontend envía como `Authorization: Bearer`; refresh en cookie `HttpOnly; SameSite=Strict` con ruta `/api/v1/auth`. Elimina el CSRF en todas las rutas salvo el refresh, que queda protegido por SameSite=Strict.
  - PD-19: sin duración absoluta.
  - **PD-07 (interino):** se valida la lectura literal «8 caracteres alternados letra/número», sin fijar con qué empieza: `a1b2c3d4` y `1a2b3c4d` son válidos. Se ajustará cuando se responda PD-07.
  - **Refresh y actividad:** el refresh **no** cuenta como actividad. Si contara, el frontend mantendría la sesión viva indefinidamente aunque nadie la use.
  - **Tras cambiar la contraseña, la sesión se cierra** y hay que volver a iniciar sesión.

## Requisitos cubiertos
REQ-AUTH-01..10, 13..18 (de 11 y 12, la parte de BD) · REQ-AUD-07 en la autenticación · REQ-IAM-05 (condiciones 1–4) · REQ-USER-04 (unicidad y normalización).

## Criterios de aceptación
1. `bootstrap-admin` crea un administrador con temporal y `debe_cambiar`. El 3.er intento falla, tanto en la CLI como en la BD.
2. Primer login → token restringido. Con él, `/me` responde 403 `PASSWORD_CHANGE_REQUIRED`. Tras cambiar la contraseña, la sesión se cierra y el nuevo login da acceso completo.
3. La política rechaza: < 12 caracteres, falta de una clase, contraseña que contiene el usuario de red y cualquiera de las 5 últimas.
4. Usuario inexistente, contraseña errónea o cuenta inactiva → 401 con el mismo mensaje genérico.
5. El 4.º fallo no bloquea; el 5.º sí (423). Bloqueado incluso con la contraseña correcta; a los 15 min se desbloquea. El estado sigue `ACTIVO`.
6. Un nuevo login invalida el token de la sesión anterior (401).
7. Sin actividad durante 15 min → 401 y la sesión queda con `INACTIVIDAD`.
8. El refresh rota; reutilizar un refresh revoca la sesión.
9. El logout invalida el token y el refresh.
10. Usuario inactivado con un token vigente → 401 en la siguiente petición.
11. Auditoría caída → login 503 y no se crea ninguna sesión.
12. Redis caído → 503.
13. Ni contraseñas, ni hashes, ni tokens en logs, auditoría o respuestas.

## Resultado (ejecutado el 2026-11-10)

| # | Criterio | Resultado |
|---|---|---|
| 1 | Bootstrap con temporal y `debe_cambiar`; el 3.º falla (CLI y BD) | OK: integración, y E2E vía CLI en el contenedor; el trigger rechaza al 3.º incluso al owner |
| 2 | Token restringido → `/me` 403; cambio → la sesión se cierra → nuevo login completo | OK (integración + E2E vía Nginx) |
| 3 | Política (longitud, clases, usuario de red, últimas 5) | OK; el historial se purga a 5 |
| 4 | Mensaje genérico (inexistente / contraseña errónea / inactivo / pendiente) | OK: mismo código y mensaje |
| 5 | 4.º fallo 401, 5.º 423; bloqueado aun con la contraseña correcta; desbloqueo; estado `ACTIVO` | OK; `bloqueado_hasta` ≈ +15 min; el mensaje no indica minutos |
| 6 | Un nuevo login invalida la sesión anterior | OK (`REEMPLAZADA`; una sola sesión abierta en BD) |
| 7 | Inactividad | OK: TTL deslizante con actividad real; `/auth/session` no lo extiende; expirada → 401 + `INACTIVIDAD` |
| 8 | Rotación y reutilización del refresh | OK: reutilizar revoca toda la sesión (`REUSO_REFRESH`) |
| 9 | Logout | OK: access y refresh invalidados |
| 10 | Usuario inactivado con token vigente | OK: 401 + `INHABILITACION` |
| 11 | Auditoría caída | OK: 503, sin sesión en BD ni en Redis |
| 12 | Redis caído | OK: 503 en login y en peticiones autenticadas |
| 13 | Sin secretos | OK: contraseñas, tokens, refresh y hashes ausentes en logs, auditoría y respuestas |

- **Pruebas:** `ruff` sin hallazgos; 45 unitarias/API; 33 de integración (15 de la Fase 2 + 18 de la Fase 3).
- **E2E vía Nginx (ambiente test):** 13/13, incluidos la IP real registrada en la sesión y el límite por IP en `/auth/login` (429).
- **Stack base:** migración `0001 → 0002` aplicada sobre los datos existentes; `ready` OK; cadena de auditoría íntegra; 0 secretos en logs.

**Defecto encontrado y corregido:** la IP del cliente no se validaba antes de guardarla en columnas `inet`. Un valor no IP (cabecera manipulada, cliente de pruebas) provocaba un 500. Ahora se valida con `ipaddress` y se guarda `NULL` si no es válida.

**Pendiente / no verificado:**
- CI en GitHub (rama sin publicar).
- Los endpoints administrativos de reset de contraseña, revocación de sesión y actividad pasan a la Fase 4 (requieren permisos).
- El cierre en BD de sesiones abandonadas (sin nueva petición ni nuevo login) se hará con el worker en la Fase 7. Mientras tanto, Redis las invalida igualmente a los 15 min.
- **En el stack base no se creó ningún administrador**: debe crearlos el responsable con `make bootstrap-admin`.
