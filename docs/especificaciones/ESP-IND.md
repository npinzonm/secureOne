# ESP-IND · Indicium Insight — Shell del módulo

> **Reglas de negocio APLAZADAS (D-IND-001).** Este documento solo define el contenedor del módulo, permitido por P §10.

## Qué se construye en v1.0 (APROBADO)
- Registro del módulo `IND` en la tabla `modulo` (activable, ordenable y asignable).
- Entrada en la navegación y en el dashboard, visible solo si el módulo está asignado y activo.
- Ruta frontend `/indicium` con una pantalla informativa: «Módulo en levantamiento funcional».
- Punto de extensión en el backend: carpeta `modules/indicium/` con un router vacío registrado bajo `/api/v1/indicium`, protegido por la verificación de módulo y sin endpoints de negocio.

## Qué NO se construye (APLAZADO)
- Entidades KPI/KGI, metas, periodicidad, responsables, captura, validación, aprobación de resultados, históricos, dashboards, semaforización, exportaciones Excel/PDF y notificaciones de indicadores.
- Permisos `IND.*`.
- Los perfiles "Responsable" y "Visualizador".

## Conflicto pendiente para el levantamiento
- **C-04:** M §7.1 excluye la carga de Excel como mecanismo de captura; P §10 incluye "carga masiva". Debe resolverse en el levantamiento funcional específico.
