# ESP-TH · Especificación funcional — Integración Talento Humano

> **Estado del documento: PROPUESTO. La implementación (Fase 8) está BLOQUEADA hasta definir el contrato de archivos (PD-09).**
> Lo que sigue son las reglas APROBADAS (P §6.3, §8) y el comportamiento propuesto alrededor de ellas. **No se definen columnas**: definirlas sería inventarlas.

## 1. Casos de uso

| ID | Caso de uso |
|---|---|
| CU-TH-01 | Recibir un archivo de planta activa (diaria) o de retirados (semanal) |
| CU-TH-02 | Consultar ejecuciones, estadísticas, validaciones y errores por fila |
| CU-TH-03 | Consultar propuestas versionadas |
| CU-TH-04 | Decidir alta normal o excepcional de un funcionario nuevo detectado |
| CU-TH-05 | Gestionar alertas (usuario ausente, archivo no recibido, duplicado, reintentos agotados) |
| CU-TH-06 | Reprocesar con nueva carga y motivo |

## 2. Reglas APROBADAS
1. La planta de retirados tiene prioridad sobre la activa si llegan juntas.
2. Una coincidencia **inequívoca** por identificación con un usuario activo genera una solicitud de inhabilitación; nunca se inhabilita automáticamente.
3. Usuario activo ausente de la planta activa → una alerta por periodo continuo de ausencia; sin cambios de estado ni permisos. Si reaparece y vuelve a faltar, se genera una alerta nueva.
4. Archivo diario no recibido → alerta tras el umbral configurable (inicialmente 4 h desde la hora habitual), sin repetir en el mismo periodo.
5. Se valida estructura, columnas, formato, integridad y duplicados. Procesamiento parcial: un error estructural rechaza toda la ejecución.
6. Se conservan resultados, estadísticas, errores, propuestas y ejecuciones. **El original se elimina tras procesarse.**
7. Un archivo duplicado no se reprocesa automáticamente. El reproceso exige nueva carga y motivo y crea una ejecución vinculada.
8. Hasta 3 reintentos técnicos (1, 5 y 15 min) idempotentes; al agotarlos, se registra el error y se notifica.
9. Los funcionarios nuevos no crean cuentas: el admin decide alta normal o excepcional.
10. Los catálogos se sincronizan solo desde TH; los elementos ausentes pasan a INACTIVO.
11. Empresa se descarta al leer y no se almacena en ninguna forma, ni siquiera en los errores por fila.

## 3. Comportamiento PROPUESTO
- **Duplicado** = mismo SHA-256 de contenido y mismo tipo de planta.
- **Idempotencia de reintentos:** cada ejecución tiene un id; las propuestas y solicitudes se crean con una clave única `(ejecucion_id, clave_negocio)`.
- **Archivo en tránsito:** volumen temporal no persistente. Se borra en `finally` tras el procesamiento, sea cual sea el resultado, y queda registrado `archivo_eliminado_en`.
- **"Hora habitual":** parámetro `th.hora_habitual` (sin valor por defecto; lo fija el admin).

## 4. Preguntas abiertas (PD-09, PD-10)
1. Columnas, tipos y formatos de cada planta; nombre de la hoja; convención de nombres de archivo.
2. ¿Qué es una "coincidencia inequívoca"? ¿Basta la identificación o también se cruza el usuario de red o el nombre?
3. ¿El cargo depende del área? ¿Cómo viene el código de cargo?
4. ¿Qué cifrado usa el archivo y quién lo descifra?
5. ¿Qué cambios organizacionales de un usuario existente (cambio de área o cargo) generan una propuesta de modificación?
