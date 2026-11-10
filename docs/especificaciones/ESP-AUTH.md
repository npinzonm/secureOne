# ESP-AUTH · Especificación funcional — Autenticación y sesiones

> **Estado del documento: PROPUESTO** (generado para cubrir la falta de especificación AUTH-RN). Cada regla indica su estado; solo las marcadas APROBADO provienen de las fuentes.

## 1. Objetivo
Controlar el acceso a SecureOne con usuario de red y contraseña, sesiones únicas y expiración por inactividad, sin almacenar secretos en claro.

## 2. Actores
- **Usuario funcional**: inicia y cierra sesión, cambia su contraseña.
- **Administrador** (máx. 2): genera contraseñas temporales y revoca sesiones.
- **Operador de despliegue**: ejecuta el bootstrap.

## 3. Casos de uso

| ID | Caso de uso | Actor | Resultado |
|---|---|---|---|
| CU-AUTH-01 | Iniciar sesión | Usuario | Sesión única creada o rechazo |
| CU-AUTH-02 | Renovar tokens | Sistema (frontend) | Par de tokens rotado |
| CU-AUTH-03 | Cerrar sesión | Usuario | Sesión finalizada `LOGOUT` |
| CU-AUTH-04 | Cambiar contraseña (obligatorio o voluntario) | Usuario | Nueva contraseña; `debe_cambiar=false` |
| CU-AUTH-05 | Generar contraseña temporal (recuperación) | Admin | Temporal mostrada **una sola vez** al admin; sesiones del usuario revocadas |
| CU-AUTH-06 | Revocar sesión de un usuario | Admin | Sesión finalizada `REVOCADA_ADMIN` |
| CU-AUTH-07 | Consultar actividad de un usuario | Admin | Último ingreso, historial, intentos, sesión activa |
| CU-AUTH-08 | Bootstrap de administradores | Operador | 2 cuentas admin con temporal |
| CU-AUTH-09 | Expirar por inactividad | Sistema | Sesión finalizada `INACTIVIDAD` |

## 4. Reglas

| # | Regla | Estado | Fuente |
|---|---|---|---|
| R1 | El identificador de login es el usuario de red, normalizado (trim, minúsculas). | APROBADO | P §5, §6.1 |
| R2 | Contraseña: ≥ 12 caracteres, con mayúscula, minúscula, número y carácter especial. | APROBADO | P §5 |
| R3 | La contraseña no puede contener ni igualar el usuario de red. | APROBADO ("coincidir"); "contener" es PROPUESTO | P §5 |
| R4 | No se reutilizan las últimas 5 contraseñas; la temporal actual cuenta como una de ellas. | APROBADO / PROPUESTO | P §5 |
| R5 | No hay vencimiento periódico. | APROBADO | P §5 |
| R6 | Con `debe_cambiar=true`, el login emite un token **restringido** válido solo para CU-AUTH-04 y logout. | PROPUESTO | P §5 |
| R7 | 5 fallos consecutivos → `bloqueado_hasta = ahora + 15 min`; se desbloquea solo; el login correcto pone el contador a 0; el estado Activo/Inactivo no cambia. | APROBADO | P §5 |
| R8 | Los intentos sobre una cuenta bloqueada no amplían el bloqueo y se auditan como `REJECTED`. | PROPUESTO | — |
| R9 | 15 min sin peticiones autenticadas → sesión cerrada. Las peticiones de sondeo automático (`/auth/session`) **no** cuentan como actividad. | APROBADO / PROPUESTO | P §5 |
| R10 | Un login exitoso finaliza la sesión previa (`REEMPLAZADA`) y revoca sus tokens. | APROBADO | P §5 |
| R11 | Inhabilitar → se revocan inmediatamente la sesión y los refresh; la siguiente petición recibe 401. | APROBADO | P §5 |
| R12 | Reactivar → nueva contraseña temporal + `debe_cambiar=true`. | APROBADO | P §5 |
| R13 | El reset genera una temporal aleatoria que cumple R2, se muestra una vez al admin y nunca se registra en logs ni en auditoría. | APROBADO (sin mostrar la anterior) / PROPUESTO (mecanismo) | P §5 |
| R14 | Bootstrap: comando CLI interactivo, idempotente, que falla si ya existen 2 administradores activos. Pide usuario de red, identificación, nombre y correo y genera una temporal aleatoria mostrada solo en la terminal. Sin valores por defecto. Evento `AUTH_BOOTSTRAP` con actor `SYSTEM`. | APROBADO (requisito) / PROPUESTO (mecanismo) | P §5 |
| R15 | El frontend muestra un aviso antes de la expiración por inactividad. El tiempo de aviso es PROPUESTO: 1 minuto antes. | PROPUESTO | — |
| R16 | Se registra último ingreso, última actividad, historial de sesiones (con IP y user-agent) e intentos fallidos. | APROBADO | M §11.3 |

## 5. Mensajes (PD-17, PROPUESTO)

| Situación | HTTP | Mensaje al usuario |
|---|---|---|
| Usuario inexistente / contraseña errónea / cuenta inactiva / alta pendiente | 401 | «Usuario o contraseña inválidos.» |
| Cuenta bloqueada temporalmente | 423 | «Cuenta bloqueada temporalmente por intentos fallidos. Intente más tarde.» |
| Debe cambiar la contraseña | 200 (token restringido) | «Debe establecer una nueva contraseña para continuar.» |
| Sesión expirada o reemplazada | 401 | «Su sesión finalizó. Inicie sesión nuevamente.» |
| Auditoría no disponible | 503 | «Servicio no disponible temporalmente. Intente más tarde.» |

## 6. Criterios de aceptación
1. El 5.º intento fallido bloquea durante 15 min; el 4.º no bloquea; a los 15 min y 1 s se puede iniciar sesión.
2. Tras un login en otro navegador, el token anterior recibe 401.
3. Tras 15 min sin actividad, cualquier petición recibe 401 y la `Sesion` queda con `INACTIVIDAD`.
4. Ningún log, evento ni respuesta contiene la contraseña, el hash, el token o la cookie (T-SEC-18).
5. El bootstrap no crea un 3.er administrador.
6. Una contraseña igual a cualquiera de las 5 anteriores se rechaza con 422.
