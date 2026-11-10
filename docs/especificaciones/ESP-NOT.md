# ESP-NOT · Especificación funcional — Notificaciones

> **Estado del documento: PROPUESTO.** Las notificaciones de indicadores (M §13.1–13.2) están **APLAZADAS** con Indicium (C-05).

## 1. Reglas (APROBADAS, P §9.2 y M §13.3)
- Canales: bandeja interna y correo.
- Los dos administradores son destinatarios obligatorios y no se pueden quitar manualmente.
- Generación y entrega independientes: el fallo de un canal no afecta al otro.
- Reintentos con estados registrados. Al agotarlos, alerta técnica.
- Un fallo de notificación **no revierte** una operación ya aprobada y auditada.
- Sin secretos ni datos sensibles innecesarios.
- Plantillas reutilizables, control de duplicados e identificación del evento de origen.

## 2. Catálogo inicial de eventos notificados (PROPUESTO)

| Evento origen | Destinatarios | Canales | Contenido mínimo |
|---|---|---|---|
| Solicitud creada (manual o TH) | Ambos admins | Bandeja + correo | Número, tipo, usuario de red objetivo y enlace |
| Solicitud aprobada / rechazada / cancelada / superada | Ambos admins | Bandeja + correo | Número, resultado, actor y motivo |
| Ejecución TH completada / parcial / rechazada | Ambos admins | Bandeja + correo | Tipo, estadísticas y enlace |
| Archivo TH duplicado | Ambos admins | Bandeja + correo | Tipo y fecha |
| Archivo diario no recibido (umbral configurable, inicialmente 4 h) | Ambos admins | Bandeja + correo | Fecha esperada |
| Usuario activo ausente de la planta | Ambos admins | Bandeja + correo | Usuario de red (sin identificación completa) |
| Reintentos TH agotados | Ambos admins | Bandeja + correo | Ejecución y error resumido |
| Notificación agotada (alerta técnica) | Ambos admins | **Solo bandeja** (evita bucles de correo) | Notificación afectada |
| Incidente de auditoría registrado | Ambos admins | Bandeja + correo | Intervalo y número de operaciones bloqueadas |
| Bloqueo de cuenta por intentos | — | — | **No se notifica** (no consta en las fuentes; solo se audita) |

**Nunca** se envían por correo contraseñas temporales: se muestran solo en pantalla al admin (ESP-AUTH R13).

## 3. Parámetros (PROPUESTO, PD-11)
- Reintentos de entrega: 1, 5, 15 y 60 min, y después `AGOTADA`.
- Clave de duplicado: `(tipo_evento, id_origen, destinatario, canal)`.
- SMTP: host, puerto, usuario y remitente por variables de entorno; contraseña SMTP solo en `.env` o un secreto.
- Dev/test: Mailpit.
