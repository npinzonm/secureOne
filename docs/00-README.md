# SecureOne v1.0 — Diseño técnico previo al código

> **Estado de este paquete de diseño: PROPUESTA TÉCNICA A VALIDAR.**
> Ningún modelo de datos, endpoint, permiso o especificación de este directorio está aprobado hasta que el responsable del proyecto lo valide expresamente.

## Contenido

| Doc | Entregable | Archivo |
|---|---|---|
| A | Matriz de requisitos, estado y conflictos | [01-matriz-requisitos.md](01-matriz-requisitos.md) |
| B + C | Arquitectura lógica, estructura de carpetas, diagramas de componentes y flujos | [02-arquitectura.md](02-arquitectura.md) |
| D | Modelo conceptual de datos trazado a requisitos | [03-modelo-datos.md](03-modelo-datos.md) |
| E | Matriz de endpoints con permiso, auditoría y pruebas | [04-api-endpoints.md](04-api-endpoints.md) |
| F | Decisiones técnicas pendientes con recomendación | [05-decisiones-pendientes.md](05-decisiones-pendientes.md) |
| — | Especificaciones funcionales por módulo (generadas, PROPUESTAS) | [especificaciones/](especificaciones/) |

## Fuentes leídas (íntegramente)

| Código | Documento | Fecha | Uso |
|---|---|---|---|
| **P** | `SecureOne_Paquete_Transferencia_Tecnica_v1.0.docx` | 04/11/2026 | Fuente prevalente (decisiones más recientes) |
| **M** | `SecureOne_Documento_Maestro_Contexto_Requerimientos_Generales_v1.0.docx` | 02/11/2026 | Línea base general |
| **ER** | `Diagrama_de_entidad_relacion_v1.pdf` | s/f (anterior) | Referencia; no es modelo aprobado (P §12) |
| **CL** | `SecureOne_Diagrama_Clases_Dominio.pdf` | s/f (anterior) | Referencia; varias reglas superadas |
| **SQ** | `Diagrama_de_secuencia.png` (inicio de sesión) | s/f (anterior) | Referencia; varias reglas superadas |
| **PA** | `Proyecto_Plataforma_Ciberseguridad_Practica_III.pdf` | 09/2026 | Contexto académico y objetivos |
| — | `SecureOne_Prompt_Maestro_IA_Desarrolladora.txt` | — | Instrucciones de trabajo (idénticas a P §16) |

**No existen** (confirmado por el responsable): especificación literal por requisito (AUTH-RN, USER-RN, …) ni registro maestro de pendientes (GEN-PEN, …). Por instrucción del responsable, este paquete **genera** lo no documentado, siempre etiquetado como PROPUESTO.

## Convenciones

**Estados**

| Estado | Significado |
|---|---|
| **APROBADO** | Consta explícitamente en P o M (o en ambos) y no fue superado por una decisión posterior. |
| **PROPUESTO** | Generado en este diseño para completar un vacío. Requiere validación. |
| **PENDIENTE** | Decisión necesaria no tomada. Bloquea solo la parte dependiente. |
| **APLAZADO** | Fuera de v1.0 por decisión explícita, o diferido hasta un levantamiento específico. |
| **EXCLUIDO** | Fuera de alcance por decisión explícita. |

**Identificadores provisionales.** Como no existe el registro literal de requisitos, se usan IDs con prefijo `REQ-` (p. ej. `REQ-AUTH-07`) para **evitar colisión** con los IDs originales `AUTH-RN`/`AUTH-PEN`. Si el registro original aparece, se mapearán sin renumerar.

Otros prefijos: `C-nn` conflicto · `PD-nn` decisión pendiente · `CU-XXX-nn` caso de uso · `T-XXX-nn` prueba · `EV-XXX` evento de auditoría.

**Regla de precedencia aplicada:** ante contradicción, prevalece la decisión aprobada más reciente (P > M > diagramas). Todo conflicto queda registrado en la sección de conflictos de [01-matriz-requisitos.md](01-matriz-requisitos.md#conflictos-detectados).

## Observación sobre la fuente PA

El capítulo 1 (Introducción) de `Proyecto_Plataforma_Ciberseguridad_Practica_III.pdf` menciona «el caso de estudio de la empresa TechSecure S.A.», «ethical hacking (OSSTMM)» y «fingerprinting», lo que no corresponde a SecureOne. Al parecer el texto se copió de otro trabajo. No afecta el diseño, pero conviene corregirlo en el documento académico.
