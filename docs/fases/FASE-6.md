# Fase 6 — Resolución de solicitudes (aprobar, rechazar, cancelar, aplicar)

Rama: `feature/fase-6-solicitudes`, creada desde `develop` (que ya incluye las Fases 1–5).

## Alcance
| Caso de uso | Endpoint | Permiso |
|---|---|---|
| CU-APR-02 Aprobar y aplicar de forma atómica | `POST /admin/requests/{id}/approve` | `ADM.SOLICITUD.APROBACION` |
| CU-APR-03 Rechazar con motivo | `POST /admin/requests/{id}/reject` | `ADM.SOLICITUD.APROBACION` |
| CU-APR-04 Cancelar con motivo | `POST /admin/requests/{id}/cancel` | `ADM.SOLICITUD.CREACION` |
| Solicitud vinculada (corrección tras cancelar o rechazar) | `solicitud_vinculada_id` en las 5 operaciones de la Fase 5 | Los de la Fase 5 |
| Historial por atributo y de estados del usuario | `GET /admin/users/{id}/history` | `ADM.USUARIO.CONSULTA` |

### Qué aplica cada tipo al aprobarse
| Tipo | Efecto |
|---|---|
| `ALTA_USUARIO` | `PENDIENTE_ALTA → ACTIVO`; contraseña temporal (se muestra **una vez** al aprobador) con `debe_cambiar`; módulos asignados |
| `MODIFICACION_USUARIO` | Aplica todos los atributos o ninguno |
| `MODULOS_USUARIO` | Deja exactamente el conjunto solicitado; las asociaciones quitadas quedan INACTIVAS |
| `INHABILITACION_USUARIO` | `ACTIVO → INACTIVO`; sesión y refresh revocados de inmediato |
| `REACTIVACION_USUARIO` | `INACTIVO → ACTIVO`; nueva temporal (se muestra una vez) con cambio obligatorio |

## Reglas
**APROBADAS (D-APR-001/002, P §5–§7):**
- una sola aprobación; **cualquiera de los dos administradores**, incluido el solicitante (**autoaprobación**);
- sin doble aprobación y sin estado «esperando al otro administrador»;
- aplicación **todo o nada**;
- rechazo y cancelación con motivo;
- una solicitud resuelta no se vuelve a resolver;
- inhabilitar invalida las sesiones de inmediato;
- reactivar exige contraseña temporal y cambio obligatorio;
- máximo 2 administradores activos.

**PROPUESTAS:**
- **Revalidación al aprobar:** se comprueba que cada `valor_anterior` siga coincidiendo con el valor actual (ESP-APR R8) y que el perfil, los catálogos y los módulos sigan activos. Si no, 409 y la solicitud queda PENDIENTE para cancelarla y crear otra vinculada.
- **Alta rechazada o cancelada:** el registro pasa a `INACTIVO` con motivo y se conserva (ESP-ADM-USR R5).
- **Corrección de un alta (vacío en las fuentes):** el usuario de red y la identificación son únicos y no se reutilizan. Para corregir un alta rechazada o cancelada se crea una nueva solicitud **vinculada** que **reutiliza el mismo registro**, solo si ese usuario nunca llegó a activarse (no tiene credencial). Así se cumplen a la vez «cancelar y crear otra vinculada» (REQ-APR-06) y la unicidad (REQ-USER-04).
- **Historial de estados del usuario:** tabla `app.usuario_estado_historial` con actor, fecha, motivo y solicitud. Solo admite inserciones (REQ-USER-08).
- No dejar al sistema sin administradores activos (R9), revalidado al aprobar.

## Fuera de alcance
- Notificaciones a los administradores en cada transición (REQ-APR-08 → Fase 7).
- Solicitudes de origen TH y estado `SUPERADA` (Fase 8).

## Criterios de aceptación
1. Un administrador crea y **autoaprueba** su solicitud. El evento registra solicitante = aprobador y no existe ningún estado intermedio de segunda aprobación.
2. Aprobar una ALTA activa al usuario, que puede iniciar sesión con la temporal (cambio obligatorio) y ve sus módulos. La temporal no queda en BD, auditoría ni logs.
3. Aprobar una MODIFICACIÓN aplica todos los atributos. Si uno ya no coincide con su `valor_anterior`, no se aplica ninguno (409) y la solicitud sigue PENDIENTE.
4. Aprobar una INHABILITACIÓN corta la sesión activa en la siguiente petición (401) y registra el historial con motivo.
5. Aprobar una REACTIVACIÓN obliga a cambiar la contraseña.
6. Rechazar o cancelar sin motivo → 422. Rechazar un alta deja el registro `INACTIVO`. Resolver una solicitud ya resuelta → 409.
7. Una corrección vinculada de un alta reutiliza el registro. Una vinculación inválida (otra entidad o solicitud no resuelta) → 422.
8. Si falla la aplicación o la auditoría, nada cambia: la solicitud sigue PENDIENTE y la entidad intacta.
9. El historial muestra cada solicitud con sus ítems (anterior → nuevo), su resolución y los cambios de estado.
10. Las rutas nuevas quedan cubiertas por T-SEC-00 y por la batería negativa.

## Resultado (ejecutado el 2026-11-10)

| # | Criterio | Resultado |
|---|---|---|
| 1 | Autoaprobación sin doble aprobación | OK: `autoaprobacion = true`, solicitante = aprobador; las restricciones de la tabla no contienen ningún estado intermedio; el otro administrador también puede aprobar |
| 2 | Alta aprobada | OK: `ACTIVO`; inicio de sesión con la temporal → cambio obligatorio → ve sus módulos; la temporal no aparece en BD, auditoría ni logs; respuesta con `no-store` |
| 3 | Modificación todo o nada | OK: con un snapshot desactualizado → 409 `SNAPSHOT_MISMATCH`, nada aplicado, sigue PENDIENTE; cancelar + vinculada → aplica todos los atributos |
| 4 | Inhabilitación | OK: el token del usuario pasa de 200 a 401 tras aprobar; sesión `INHABILITACION`; historial con motivo |
| 5 | Reactivación | OK: la contraseña anterior deja de servir; temporal con cambio obligatorio |
| 6 | Rechazo y cancelación | OK: sin motivo o con motivo corto → 422; un alta rechazada pasa a `INACTIVO`; resolver de nuevo → 409 `REQUEST_ALREADY_RESOLVED` |
| 7 | Corrección vinculada de un alta | OK: reutiliza el mismo registro; sin vínculo → 409 (identificador ya usado); vínculo de otra entidad o a una solicitud no resuelta → 422; reactivar un alta nunca activada → 422 |
| 8 | Fail-closed | OK: auditoría caída al aprobar → 503, solicitud PENDIENTE y usuario intacto; recuperado el servicio, se aprueba |
| 9 | Historial | OK: solicitudes con ítems (anterior → nuevo), resolución y vínculo; estados con actor, fecha, motivo y solicitud |
| 10 | T-SEC | OK: T-SEC-00 y la batería de todos los métodos cubren las rutas nuevas |

Además: los módulos quitados quedan INACTIVOS (historia); máximo de 2 administradores (409 `ADMIN_LIMIT`, sin efectos); no se aprueba la inhabilitación del último administrador activo.

- **Pruebas:** `ruff` sin hallazgos; 53 unitarias/API; 72 de integración (Fases 2–6).
- **Stack base:** migración `0004 → 0005` aplicada; `approve` sin token → 401; cadena íntegra; 0 secretos en logs.
- **CI de GitHub:** Fases 4 y 5 (PR y `develop`) en *success*.

**Pendiente:**
- Notificaciones a ambos administradores en cada transición (REQ-APR-08 → Fase 7).
- Solicitudes de origen TH y estado `SUPERADA` (Fase 8).
