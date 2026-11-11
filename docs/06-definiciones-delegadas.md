# Definiciones por delegación (2026-11-10)

> El responsable del proyecto indicó: «las definiciones a este punto colócalas tú». Las decisiones de este documento se adoptan con estado **DEFINIDO POR DELEGACIÓN**:
> - son vinculantes para la implementación de v1.0;
> - **no provienen de las fuentes** (P/M) ni de Talento Humano;
> - deben **revisarse** cuando exista el contrato real de archivos o la especificación UX.
>
> Cada definición es reversible y está aislada en código (constantes o parámetros) para facilitar su cambio.

## DD-01 · PD-07 Patrón del usuario de red
Lectura literal de P §6.1: **8 caracteres alternando letra y número, empezando por cualquiera de los dos** (`a1b2c3d4` o `1a2b3c4d`). Solo se aceptan letras ASCII; se guarda en minúsculas. Es lo que ya validan el código y la BD desde la Fase 3.

## DD-02 · PD-08 Alta NORMAL / EXCEPCIONAL
| Tipo | Definición | Regla |
|---|---|---|
| **NORMAL** | La persona figura en la **última planta activa procesada** de TH | Si existe al menos una ejecución de planta activa COMPLETADA o PARCIAL, la identificación debe estar en ella; si no, el alta se rechaza (422) indicando que debe tramitarse como EXCEPCIONAL |
| **EXCEPCIONAL** | La persona **no** figura en la planta activa (p. ej., ingreso aún no reportado por TH o personal autorizado temporalmente) | **Motivo obligatorio** (mín. 10 caracteres); queda resaltada en solicitudes, historial y filtros |

Mientras no se haya procesado ninguna planta, la regla de NORMAL no puede verificarse y no se aplica.

## DD-03 · PD-09 Contrato de archivos de Talento Humano
**Formato general:**
- `.xlsx` (Office Open XML) **sin macros**, de máximo **10 MB** y **100 000 filas** de datos.
- La primera hoja es la que se lee.
- La fila 1 contiene los **encabezados**: se comparan sin distinguir mayúsculas ni tildes y sin espacios extremos.
- Columnas desconocidas: se ignoran y se informan en las estadísticas.
- **La columna `EMPRESA`, si existe, nunca se lee** (REQ-TH-12).

**Convención de nombre (informativa; no se rechaza por el nombre):** `planta_activa_AAAAMMDD.xlsx` y `planta_retirados_AAAAMMDD.xlsx`.

### Planta activa (diaria)
| Columna | Obligatoria | Formato |
|---|---|---|
| `IDENTIFICACION` | Sí | `^[A-Za-z0-9-]{3,20}$`; única en el archivo |
| `NOMBRES` | Sí | Texto ≤ 100 |
| `PRIMER_APELLIDO` | Sí | Texto ≤ 50 |
| `SEGUNDO_APELLIDO` | No | Texto ≤ 50 |
| `CORREO` | No | Email ≤ 150 |
| `USUARIO_RED` | No | Patrón DD-01 |
| `CODIGO_GERENCIA` / `GERENCIA` | Sí | Código ≤ 40 / nombre ≤ 150 |
| `CODIGO_AREA` / `AREA` | Sí | Código ≤ 40 / nombre ≤ 150; un mismo código de área no puede pertenecer a dos gerencias |
| `CODIGO_CARGO` / `CARGO` | Sí | Entero > 0 / nombre ≤ 150 |

### Planta de retirados (semanal)
| Columna | Obligatoria | Formato |
|---|---|---|
| `IDENTIFICACION` | Sí | Igual que arriba |
| `FECHA_RETIRO` | Sí | Fecha (celda de fecha de Excel o `AAAA-MM-DD`) |
| `USUARIO_RED` | No | Si viene, debe coincidir con el usuario (ver DD-04) |
| `NOMBRES`, `PRIMER_APELLIDO` | No | Informativas |

### Validación
- **Error estructural → se rechaza toda la ejecución:**
  - el archivo no es un .xlsx válido, contiene macros o está vacío;
  - falta una columna obligatoria;
  - supera el límite de filas.
- **Error de fila → la fila se excluye y el resto se procesa** (procesamiento parcial): formato inválido, obligatorio vacío o identificación duplicada (todas las apariciones quedan en error).

## DD-04 · PD-09 Reglas de conciliación
| Situación (planta activa) | Acción |
|---|---|
| Catálogos | Gerencias, áreas y cargos se crean o actualizan por **código**. Los que no aparecen en la planta procesada pasan a **INACTIVO** (solo si la ejecución no fue rechazada) |
| Identificación sin usuario en SecureOne | **Propuesta versionada `NUEVO_FUNCIONARIO`**: no se crea la cuenta; el administrador decide NORMAL o EXCEPCIONAL y eso crea la solicitud de alta |
| Usuario ACTIVO cuya gerencia, área o cargo difiere | **Propuesta versionada `CAMBIO_ORG`**, presentada como solicitud `MODIFICACION_USUARIO` de origen TH. Si cambia de nuevo en otra ejecución, la solicitud pendiente pasa a `SUPERADA` y se crea la nueva versión |
| Usuario ACTIVO que no aparece | Alerta `USUARIO_AUSENTE`, **una por periodo continuo**; se cierra cuando reaparece. No cambia el estado ni los permisos |

| Situación (planta de retirados) | Acción |
|---|---|
| **Coincidencia inequívoca**: la identificación corresponde a exactamente un usuario ACTIVO y, si el archivo trae `USUARIO_RED`, coincide | Solicitud `INHABILITACION_USUARIO` de origen TH (motivo: «Retiro reportado por TH, fecha X») |
| Identificación de un usuario ACTIVO pero con `USUARIO_RED` distinto | **No es inequívoca**: la fila queda OMITIDA con motivo `COINCIDENCIA_AMBIGUA`, sin solicitud |
| Usuario inexistente o ya INACTIVO | OMITIDA (informativa) |
| Ya existe una solicitud pendiente sobre el usuario | OMITIDA (`SOLICITUD_PENDIENTE`) |

Las ejecuciones de retirados **se procesan antes** que las de planta activa (prioridad, REQ-TH-02).

## DD-05 · PD-10 Canal de ingreso y descifrado
- **Ingreso:** carga manual por la API/UI (`POST /admin/th/files`). No hay integración con SharePoint en v1.0.
- **Cifrado:** el prototipo recibe el archivo **ya descifrado**; el descifrado operativo es responsabilidad del proceso de TH (fuera de v1.0).
- **Procesamiento:** asíncrono en el worker. El archivo queda en un volumen temporal del contenedor y **se elimina al terminar** (estado final), conservando solo su SHA-256 (REQ-TH-08).
- **Reintentos técnicos:** a 1, 5 y 15 min (REQ-TH-10). Agotados → `FALLIDA` + notificación + registro de error.
- **Duplicado:** el mismo SHA-256 y tipo de una ejecución ya procesada → 409 y notificación. Para reprocesar hay que volver a cargar el archivo con `reproceso_de` y motivo (REQ-TH-09).
- **Archivo diario no recibido:** el worker alerta cuando han pasado `th.umbral_alerta_horas` (4) desde `th.hora_habitual` en la zona `th.zona_horaria` (**America/Bogota**) sin una planta activa del día. Una alerta por día; se cierra cuando llega el archivo.

## DD-06 · PD-11 Correo de los administradores
Se usa el campo `correo` del usuario. El SMTP del prototipo es Mailpit; un SMTP real se configura por variables de entorno.

## DD-07 · PD-22 Experiencia de usuario (v1.0)
- **Objetivo:** pantallas **funcionales y sobrias** para operar y validar todos los flujos. No es un diseño visual de marca.
- **Estilo:** sistema propio mínimo, sin dependencias de UI:
  - tipografía del sistema;
  - paleta neutra con un color de acento azul petróleo;
  - modo claro y oscuro según el sistema;
  - contraste AA;
  - foco visible.
- **Idioma:** español; los mensajes de error vienen de la API.
- **Navegación:**
  - **login → cambio obligatorio de contraseña → dashboard de módulos** (asignados y activos, en orden global; mensaje si no hay ninguno);
  - el módulo Administración tiene menú lateral con Usuarios, Solicitudes, Perfiles, Roles, Permisos, Módulos, Dominios, Auditoría, Errores, Talento Humano, Notificaciones y Parámetros;
  - **campana de notificaciones** en la barra superior.
- **Sesión:**
  - access token solo en memoria y refresh por cookie `HttpOnly`;
  - **aviso 60 s antes** del cierre por inactividad, con opción de seguir;
  - la actividad del usuario (no los sondeos) mantiene la sesión.
- **Contraseñas temporales:** se muestran una vez en un diálogo con «copiar» y advertencia, y nunca se guardan en el navegador.
- **Indicium Insight:** pantalla «Módulo en levantamiento funcional» (D-IND-001).
- **Responsive** hasta 360 px de ancho.
