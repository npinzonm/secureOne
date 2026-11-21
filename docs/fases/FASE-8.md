# Fase 8 — Integración con Talento Humano

Rama: `feature/fase-8-integracion-th`, creada desde `feature/fase-7-auditoria-notificaciones`.
**Contrato y reglas: DEFINIDOS POR DELEGACIÓN** ([06-definiciones-delegadas.md](../06-definiciones-delegadas.md), DD-02..DD-05). Deben revisarse con los archivos reales de TH.

## Alcance implementado
| Componente | Detalle |
|---|---|
| Migración 0007 | `ejecucion_th` (solo SHA-256 del archivo), `resultado_fila_th` (solo identificación, resultado y motivos), `propuesta_th` + `propuesta_th_version` (ID estable, una versión vigente), `alerta_th` (una abierta por periodo), vínculo `solicitud.propuesta_version_id`, plantillas de notificación TH y parámetro `th.zona_horaria` |
| Contrato (DD-03) | Lector puro: valida contenedor (.xlsx sin macros, ≤ 10 MB), encabezados normalizados, obligatorios, formatos y duplicados; **EMPRESA nunca se lee** |
| Recepción (DD-05) | `POST /admin/th/files` (multipart): validación temprana, SHA-256, duplicado → 409 + notificación, reproceso con `reproceso_de` + motivo; archivo en volumen `thfiles` con permisos 0600 |
| Procesamiento | En el **worker**, una transacción por ejecución (idempotente); **retirados antes que activa**; reintentos técnicos 1/5/15 min → `FALLIDA`; el archivo se elimina al llegar a un estado final |
| Planta activa (DD-04) | Catálogos por código (ausentes → INACTIVO); `NUEVO_FUNCIONARIO` (sin crear cuenta); `CAMBIO_ORG` como solicitud `MODIFICACION_USUARIO` de origen TH con versión vigente (la anterior → `SUPERADA`); ausencias con una alerta por periodo; cierre de la alerta de archivo no recibido |
| Retirados (DD-04) | Coincidencia inequívoca → solicitud `INHABILITACION_USUARIO` de origen TH (**nunca automática**); ambigua, inexistente, inactivo o con solicitud pendiente → OMITIDA con motivo |
| Alerta de archivo diario | Worker: `th.hora_habitual` + `th.umbral_alerta_horas` en `th.zona_horaria`; una alerta por periodo continuo |
| Decisión sobre un nuevo funcionario | `POST /admin/th/proposals/{id}/decide` (NORMAL/EXCEPCIONAL) → solicitud de alta con los datos de la versión vigente |
| DD-02 | Alta NORMAL exige figurar en la última planta activa procesada; EXCEPCIONAL exige motivo |
| Consulta | Ejecuciones, filas, propuestas con versiones y alertas |
| Aprobación | Solo es aprobable la versión vigente de una propuesta TH (REQ-APR-07) |

## Resultado (ejecutado el 2026-11-10)
| Verificación | Resultado |
|---|---|
| `ruff` | Sin hallazgos |
| Unitarias/API | 65 (7 nuevas del contrato: encabezados, filas, duplicados, EMPRESA no leída, fechas, errores estructurales, macros) |
| Integración | 87 (6 nuevas de la Fase 8) |

Las 6 pruebas nuevas de integración cubren:
- **Recepción:** validación; archivo con permisos 0600; eliminado tras procesar.
- **Planta activa completa:**
  - procesamiento parcial con estadísticas;
  - EMPRESA ausente de la BD;
  - catálogos sincronizados;
  - solicitud TH con versión;
  - propuesta de nuevo funcionario sin cuenta creada;
  - alerta de ausencia sin cambiar el estado;
  - duplicado 409 con notificación;
  - reproceso vinculado;
  - nueva versión que deja la anterior en `SUPERADA` (aprobar la superada → 409; la vigente se aplica);
  - cargo ausente → INACTIVO;
  - la alerta se cierra cuando el usuario reaparece y se abre otra cuando vuelve a faltar.
- **Decisión NORMAL** → alta aprobada con el usuario de red de la planta; reglas DD-02 (NORMAL fuera de planta → 422; EXCEPCIONAL sin motivo → 422).
- **Retirados:**
  - procesados **antes** que la planta activa;
  - coincidencia inequívoca → solicitud (el usuario sigue ACTIVO hasta aprobarla);
  - ambigua o inexistente → omitida.
- **Fallas técnicas:** reintento a ~60 s; tras 3 intentos → `FALLIDA` con notificación y registro de error.
- **Archivo diario no recibido:** sin alerta antes del umbral; una sola alerta por periodo; se cierra al llegar la planta.

**E2E real en el ambiente de pruebas:**
- carga a través de Nginx → worker en contenedor → `COMPLETADA` en ~6 s;
- volumen TH vacío después;
- propuestas y catálogos creados;
- duplicado → 409;
- 0 apariciones de «ACME»/Empresa en la BD.

**Stack base:** migración `0006 → 0007`; 7 servicios `healthy`; carga sin token → 401; cadena íntegra; 0 secretos en logs.

**Defectos encontrados y corregidos:**
1. La notificación de archivo duplicado usaba un `origen_id` de más de 64 caracteres. La generación fallaba sin afectar a la operación (D-NOT-001 funcionó), pero la notificación se perdía. Ahora el origen es el SHA-256 y cada intento duplicado lleva su propia clave de duplicado.
2. *(Herramienta de prueba, no del producto)*: mi script E2E invocaba `timeout` sobre una función de bash, que no puede ejecutar; por eso el «primer arranque fallido» de la Fase 7. El stack arranca desde cero sin problemas.

## Pendiente / a revisar con TH
- Contrato real de columnas, nombres de archivo, cifrado y reglas de conciliación (DD-03/04/05 son definiciones por delegación).
- Integración con SharePoint (fuera de v1.0).
