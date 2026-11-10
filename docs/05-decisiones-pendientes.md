# F. Decisiones técnicas pendientes

> Cada decisión lleva una recomendación. **Ninguna está aprobada** hasta que el responsable la valide.
> **Bloquea** = fase o funcionalidad que no se implementa sin la respuesta. Si dice "no bloquea", se implementará la recomendación como PROPUESTA, de forma reversible, salvo indicación contraria.

## Resumen y prioridad de respuesta

| ID | Tema | Bloquea | Prioridad de respuesta |
|---|---|---|---|
| PD-01 | Sesiones, JWT/refresh y uso de Redis | Fase 3 | **Antes de la Fase 3** |
| PD-04 | Alcance de "operación crítica" para fail-closed | Fase 3 | **Antes de la Fase 3** |
| PD-05 | Matriz directa / con aprobación | Fases 5–6 | **Antes de la Fase 5** |
| PD-06 | Modelo de la cuenta Administrador | Fase 3 | **Antes de la Fase 3** |
| PD-07 | Patrón exacto del usuario de red | Fase 4 | Antes de la Fase 4 |
| PD-08 | Significado de alta "excepcional" | Fase 5 (solo ese atributo) | Antes de la Fase 5 |
| PD-09 | Contrato de archivos TH | **Fase 8 completa** | Antes de la Fase 8 |
| PD-10 | Canal de ingreso y descifrado de TH en el prototipo | Fase 8 | Antes de la Fase 8 |
| PD-22 | Especificación UX/UI | Fase 9 (diseño final) | Antes de la Fase 9 |
| Resto | — | No bloquea | Se puede validar sobre la marcha |

---

### PD-01 · Estrategia de sesión, tokens y Redis (REQ-AUTH-08/09/10/14, P §3 y §12)
- **Opciones:**
  - (a) JWT de larga vida sin estado del lado del servidor.
  - (b) JWT corto + lista de revocación en Redis.
  - (c) **JWT corto con `sid` + sesión viva en Redis con TTL deslizante + refresh opaco rotativo en PostgreSQL.**
- **Recomendación: (c).**
  - Access JWT de **5 min** (PROPUESTO).
  - `session:{sid}` en Redis con TTL de 15 min, renovado en cada petición autenticada. Eso implementa la expiración por inactividad.
  - `user_session:{uid}` → `sid` vigente, que da una sesión por usuario.
  - El refresh es opaco, su hash se guarda en PostgreSQL, rota en cada uso, detecta reutilización y su vida no supera la de la sesión.
  - La copia histórica de la sesión queda en la tabla `Sesion`.
- **Consecuencias:**
  - Revocación inmediata (inhabilitación, nuevo login).
  - Redis pasa a ser crítico: si cae, se responde 503 (fail-closed).
  - Al reiniciar Redis se pierden las sesiones vivas y todos deben volver a iniciar sesión (aceptable en local). Persistencia AOF opcional.
- **Pendiente asociado:** ¿existe una duración **absoluta** máxima de sesión, aunque haya actividad? Las fuentes no lo dicen y **no se fija** (PD-19).

### PD-02 · Algoritmo de hash e historial de contraseñas (REQ-AUTH-02/03)
- **Recomendación:** Argon2id con los parámetros por defecto de `argon2-cffi`, configurables, y rehash transparente si cambian.
- Se guardan las **últimas 5** contraseñas y se purgan las anteriores para minimizar datos.
- **Consecuencia:** coste de CPU razonable en un PC; sin dependencia de un HSM.

### PD-03 · Aislamiento e integridad de la auditoría (REQ-AUD-04, M §11.4)
- **Opciones:**
  - (a) Tabla en el mismo esquema.
  - (b) **Mismo PostgreSQL, esquema `audit` separado, roles de BD distintos, triggers anti UPDATE/DELETE y cadena de hash.**
  - (c) Base de datos o servicio separado.
- **Recomendación: (b).** Es la única opción que permite atomicidad negocio + auditoría en una transacción y, por tanto, un fail-closed real sin transacciones distribuidas.
- **Consecuencia:** un superusuario de BD con acceso al host podría alterar datos. La cadena de hash lo hace **detectable**, no imposible.
- **Mejora futura (Azure):** exportación periódica firmada a almacenamiento inmutable.

### PD-04 · Qué operaciones son "críticas" a efectos de fail-closed (REQ-AUD-07)
- **Recomendación:** fail-closed para **toda mutación** y para todo evento de autenticación (login, logout, cambio o reset de contraseña), además de consultas sensibles y exportaciones.
- **Consecuencia:** si la auditoría no está disponible, **nadie puede iniciar sesión**. Es lo más seguro y coherente con "registrar intentos fallidos y accesos rechazados" (M §11.1).
- **Alternativa:** permitir el login sin auditoría. No se recomienda.
- **Necesito confirmación.**

### PD-05 · Matriz de operaciones directas y con aprobación (REQ-APR-10)
- **Recomendación:** ver la [matriz propuesta](especificaciones/ESP-APR.md#matriz-de-operaciones-propuesta).
  - **Con aprobación:** alta, cambios de datos, perfil o módulos de un usuario; inhabilitación; reactivación; retiro desde TH.
  - **Directas, con impacto previo y auditoría:** gestión de perfiles, roles, permisos, módulos, dominios, parámetros y orden; reset de contraseña temporal; revocación de sesión.
- **Consecuencia:** cada cambio de usuario necesita un paso extra (crear y aprobar), aunque se pueda autoaprobar en la misma pantalla.
- **Necesito confirmación** de cada fila.

### PD-06 · Modelo de la cuenta Administrador (REQ-AUTH-12/17)
- **Opciones:**
  - (a) Campo `es_admin` en el usuario, fuera de IAM.
  - (b) **Perfil de sistema protegido `ADMINISTRADOR`**, con un rol que contiene todos los permisos `ADM.*`, no editable para quitar permisos y con un máximo de 2 usuarios activos validado en BD y en el servicio.
- **Recomendación: (b).** Respeta Usuario→Perfil→Roles→Permisos (no hay permisos directos) y la regla de 2 administradores.
- **Consecuencias:**
  - Asignar el perfil ADMINISTRADOR a un tercero falla.
  - El reemplazo de un administrador (D-ADMIN-001) = inhabilitar al saliente y aprobar el alta del entrante.
- **Pregunta:** ¿el reemplazo requiere algún registro de "designación por el encargado del área" (campo o documento de soporte)?

### PD-07 · Patrón del usuario de red (REQ-USER-04)
- **Texto fuente:** «ocho caracteres alternados letra/número».
- **Ambigüedad:** ¿empieza siempre por letra (`a1b2c3d4`) o puede empezar por número (`1a2b3c4d`)? ¿Las letras son solo A–Z sin ñ ni tildes?
- **Recomendación provisional:** `^[A-Za-z][0-9][A-Za-z][0-9][A-Za-z][0-9][A-Za-z][0-9]$`, almacenado en minúsculas.
- **Necesito confirmación.**

### PD-08 · Tipo de alta "excepcional" (REQ-USER-12, REQ-TH-11)
- Aparece como filtro y como decisión ante funcionarios nuevos detectados por TH, pero no está definido.
- **Hipótesis (no adoptada):** alta de una persona que aún no figura en la planta TH.
- **Mientras tanto:** se almacena como atributo `tipo_alta` sin reglas asociadas.
- **Necesito la definición** y si implica reglas distintas (vigencia, revisión, justificación obligatoria).

### PD-09 · Contrato de archivos TH (REQ-TH-14) — **bloquea la Fase 8**
Se necesita para la planta activa y la de retirados:
- nombre y convención de los archivos;
- hoja o hojas;
- columnas exactas con tipo y formato;
- clave de identificación;
- cómo se representan gerencia, área, cargo y código de cargo, y si el cargo depende del área;
- reglas de conciliación (qué es una "coincidencia inequívoca");
- cifrado utilizado.

**Pido:** un archivo de ejemplo de cada tipo con **datos ficticios**.

### PD-10 · Canal de ingreso TH en el prototipo
- **Opciones:**
  - (a) **Carga manual desde la UI.**
  - (b) Carpeta vigilada en un volumen local.
  - (c) SharePoint real (no aplica: v1.0 no tiene integraciones corporativas).
- **Recomendación: (a)**, más un endpoint interno equivalente a (b) para simular la llegada diaria y la alerta de "archivo no recibido".
- **Descifrado:** el prototipo recibe el archivo **ya descifrado**. El descifrado operativo queda PENDIENTE.

### PD-11 · Correo y notificaciones (REQ-NOT-09)
- **Recomendación:**
  - SMTP configurable por variables de entorno; Mailpit en dev/test.
  - Reintentos de entrega a los 1, 5, 15 y 60 min (4 intentos) y luego `AGOTADA` + alerta técnica. Los valores son PROPUESTOS y configurables.
  - Catálogo inicial de eventos en [ESP-NOT](especificaciones/ESP-NOT.md).
- **Pregunta:** ¿qué dirección de correo reciben los administradores: la del campo `correo` del usuario?

### PD-12 · Ejecución de tareas en segundo plano
- **Recomendación:** un contenedor `worker` con la misma imagen, que hace polling del outbox en PostgreSQL (`SELECT … FOR UPDATE SKIP LOCKED`) y usa APScheduler para tareas periódicas.
- No se usa un broker adicional: menos piezas y PostgreSQL es la fuente de verdad.
- **Alternativa:** arq/Celery con Redis.

### PD-13 · Estructura del repositorio
- **Recomendación:** monorepo `secureone/` en GitHub, con la estructura de [02-arquitectura §B.3](02-arquitectura.md#b3-estructura-de-carpetas-monorepo-propuesto--pd-13).
- **Pregunta:** nombre del repositorio, visibilidad (privado recomendado) y cuenta u organización.

### PD-14 · Identificadores
- **Recomendación:** UUID v7 como PK (ordenables y no enumerables) y número secuencial legible solo en `Solicitud`.

### PD-15 · Relación Cargo→Perfil de los diagramas ER/CL
- **No se adopta** porque no está aprobada (C-12).
- **Pregunta:** ¿se quiere que el cargo **sugiera** un perfil al dar de alta (solo como ayuda, sin asignarlo)?

### PD-16 · Inactivar un permiso usado por perfiles activos
- **P §6.2** exige mostrar el impacto antes de confirmar. **CL regla 6** lo prohibía.
- **Recomendación:** permitirlo con impacto previo y confirmación explícita, porque P prevalece.

### PD-17 · Mensajes de autenticación
- **Recomendación:** mensaje genérico «Usuario o contraseña inválidos» para usuario inexistente, contraseña errónea y cuenta inactiva, para no permitir enumerar usuarios.
- Mensaje específico solo para el bloqueo temporal: «Cuenta bloqueada temporalmente; intente más tarde», sin indicar los minutos.
- **Necesito confirmación** (P §15 marca los mensajes como pendientes).

### PD-18 · Almacenamiento del token en el navegador
- **Recomendación:** cookies `HttpOnly` + `Secure` + `SameSite=Strict` emitidas por el backend detrás de Nginx (mismo origen), con token CSRF de doble envío.
- **Alternativa:** token en memoria + refresh en cookie.

### PD-19 · Duración absoluta de sesión y del refresh token
- No está en las fuentes y **no se fija**.
- Por defecto, la sesión dura mientras haya actividad en ventanas de 15 min.
- **Pregunta:** ¿se requiere un tope absoluto (p. ej., jornada laboral)?

### PD-20 · TLS en el entorno local
- **Recomendación:** HTTPS con certificado autofirmado o `mkcert` en Nginx para que las cookies `Secure` funcionen igual que en Azure.
- Los certificados no se versionan.

### PD-21 · Caché de permisos efectivos
- **Recomendación:** sin caché al inicio. Si hiciera falta, caché en Redis invalidada por eventos IAM.
- No se fijan métricas de rendimiento (REQ-RNF-12).

### PD-22 · UX/UI (REQ-RNF-13)
- No hay wireframes aprobados.
- **Recomendación:** pantallas funcionales sobrias (componentes accesibles, p. ej. shadcn/ui + Tailwind) para validar los flujos.
- El diseño visual final queda PENDIENTE de una especificación.
- **Pregunta:** ¿hay manual de marca o mockups?

### PD-23 · Idioma del código
- **Recomendación:** identificadores, rutas y código en inglés; textos de UI, mensajes y documentación en español.
- Los códigos de permiso y de evento se mantienen en el idioma mostrado en este diseño.

### PD-24 · Qué consultas son "sensibles" (REQ-AUD-06)
- **Recomendación:** auditar la ficha individual de un usuario, su historial de actividad, la consulta y exportación de auditoría y todas las exportaciones.
- No se auditan los listados ni los filtros.

### PD-25 · Información propia visible para el usuario funcional (REQ-USER-09)
- **Recomendación:** nombre, usuario de red, correo, gerencia, área, cargo, perfil, módulos asignados y último ingreso.
- No se muestran la identificación completa ni los roles o permisos técnicos.
- **Necesito confirmación.**

### PD-26 · Respaldos (REQ-RNF-08)
- **Recomendación:**
  - `pg_dump -Fc` diario, rotado en 7 diarios, 4 semanales y 3 mensuales.
  - Checksum SHA-256 de cada respaldo.
  - Cifrado opcional con `age` y clave fuera del repositorio.
  - Respaldo manual previo a cada migración (`make backup-pre`).
  - Prueba de restauración automatizada en CI sobre una BD efímera.
- RPO/RTO **no se fijan**.

### PD-27 · Ambientes (REQ-RNF-09)
- **Recomendación:** `dev` y `test` con archivos Compose separados, proyectos Compose y volúmenes distintos, en el mismo PC.
- `prod` local = `docker-compose.yml` base sin overrides de desarrollo, con datos y secretos propios.
- Despliegue en Azure: PENDIENTE (M §28).
