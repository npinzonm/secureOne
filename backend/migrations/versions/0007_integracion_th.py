"""Integración Talento Humano: ejecuciones, resultados por fila, propuestas versionadas, alertas.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10

Requisitos: REQ-TH-01..13, REQ-APR-07. Contrato y reglas: DD-03/DD-04/DD-05 (por delegación).
Minimización (REQ-TH-08/12): no se guarda el archivo (solo SHA-256) ni columnas como Empresa;
los resultados por fila solo conservan identificación, resultado y motivos.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLANTILLAS = [
    ("TH_EXECUTION_DONE", "SecureOne: planta {tipo} procesada (#{numero})",
     "Ejecución TH #{numero} ({tipo}): {estado}. Filas OK: {ok}; con error: {errores}; "
     "omitidas: {omitidas}. Solicitudes generadas: {solicitudes}.", "BANDEJA,CORREO"),
    ("TH_EXECUTION_REJECTED", "SecureOne: planta {tipo} rechazada (#{numero})",
     "La ejecución TH #{numero} ({tipo}) fue rechazada por error estructural: {error}.",
     "BANDEJA,CORREO"),
    ("TH_EXECUTION_FAILED", "SecureOne: falla técnica en planta {tipo} (#{numero})",
     "La ejecución TH #{numero} ({tipo}) falló tras {intentos} intentos técnicos. "
     "Revise el registro de errores.", "BANDEJA,CORREO"),
    ("TH_DUPLICATE", "SecureOne: archivo TH duplicado",
     "Se recibió nuevamente un archivo de planta {tipo} ya procesado (ejecución #{numero}). "
     "No se reprocesó.", "BANDEJA,CORREO"),
    ("TH_FILE_MISSING", "SecureOne: no llegó la planta activa del {fecha}",
     "No se recibió la planta activa del {fecha} {umbral} horas después de la hora habitual "
     "({hora}).", "BANDEJA,CORREO"),
    ("TH_USERS_ABSENT", "SecureOne: usuarios activos ausentes de la planta",
     "La ejecución TH #{numero} abrió {cantidad} alerta(s) de usuarios activos que no aparecen "
     "en la planta activa. No se modificó su estado ni permisos.", "BANDEJA,CORREO"),
]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.ejecucion_th (
          id                   uuid         PRIMARY KEY,
          numero               bigint       GENERATED ALWAYS AS IDENTITY UNIQUE,
          tipo                 varchar(10)  NOT NULL CHECK (tipo IN ('ACTIVA', 'RETIRADOS')),
          archivo_sha256       bytea        NOT NULL,
          nombre_archivo       varchar(200) NOT NULL,
          tamano               integer      NOT NULL,
          ruta_temporal        varchar(300),
          recibido_en          timestamptz  NOT NULL DEFAULT now(),
          cargado_por          uuid         REFERENCES app.usuario (id),
          estado               varchar(12)  NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN (
                                 'PENDIENTE', 'COMPLETADA', 'PARCIAL', 'RECHAZADA', 'FALLIDA')),
          intentos             smallint     NOT NULL DEFAULT 0,
          proximo_intento_en   timestamptz  NOT NULL DEFAULT now(),
          estadisticas         jsonb,
          error                text,
          ejecucion_origen_id  uuid         REFERENCES app.ejecucion_th (id),
          motivo_reproceso     text,
          finalizada_en        timestamptz,
          archivo_eliminado_en timestamptz,
          CHECK ((ejecucion_origen_id IS NULL) = (motivo_reproceso IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX ejecucion_th_sha_idx ON app.ejecucion_th (tipo, archivo_sha256)")
    op.execute("CREATE INDEX ejecucion_th_pend_idx ON app.ejecucion_th (proximo_intento_en) "
               "WHERE estado = 'PENDIENTE'")

    op.execute(
        """
        CREATE TABLE app.resultado_fila_th (
          id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
          ejecucion_id    uuid        NOT NULL REFERENCES app.ejecucion_th (id),
          fila            integer     NOT NULL,
          identificacion  varchar(20),
          resultado       varchar(8)  NOT NULL CHECK (resultado IN ('OK', 'ERROR', 'OMITIDA')),
          accion          varchar(40),
          detalle         jsonb,
          UNIQUE (ejecucion_id, fila)
        )
        """
    )
    op.execute("CREATE INDEX resultado_fila_th_ident_idx "
               "ON app.resultado_fila_th (ejecucion_id, identificacion)")

    op.execute(
        """
        CREATE TABLE app.propuesta_th (
          id              uuid         PRIMARY KEY,
          tipo            varchar(20)  NOT NULL CHECK (tipo IN ('NUEVO_FUNCIONARIO', 'CAMBIO_ORG')),
          identificacion  varchar(20)  NOT NULL,
          usuario_id      uuid         REFERENCES app.usuario (id),
          estado          varchar(10)  NOT NULL DEFAULT 'ABIERTA'
                          CHECK (estado IN ('ABIERTA', 'CERRADA')),
          motivo_cierre   varchar(200),
          creada_en       timestamptz  NOT NULL DEFAULT now(),
          actualizada_en  timestamptz  NOT NULL DEFAULT now()
        )
        """
    )
    # ID estable: una sola propuesta ABIERTA por (tipo, identificación) (REQ-APR-07).
    op.execute("CREATE UNIQUE INDEX propuesta_th_abierta_idx ON app.propuesta_th "
               "(tipo, identificacion) WHERE estado = 'ABIERTA'")
    op.execute(
        """
        CREATE TABLE app.propuesta_th_version (
          id            uuid        PRIMARY KEY,
          propuesta_id  uuid        NOT NULL REFERENCES app.propuesta_th (id),
          version       integer     NOT NULL,
          ejecucion_id  uuid        NOT NULL REFERENCES app.ejecucion_th (id),
          contenido     jsonb       NOT NULL,
          vigente       boolean     NOT NULL,
          solicitud_id  uuid        REFERENCES app.solicitud (id),
          creada_en     timestamptz NOT NULL DEFAULT now(),
          UNIQUE (propuesta_id, version)
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX propuesta_th_version_vigente_idx "
               "ON app.propuesta_th_version (propuesta_id) WHERE vigente")
    op.execute("ALTER TABLE app.solicitud ADD COLUMN propuesta_version_id uuid "
               "REFERENCES app.propuesta_th_version (id)")
    # La columna nueva también es inmutable una vez creada la solicitud.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.solicitud_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.estado <> 'PENDIENTE' THEN
            RAISE EXCEPTION 'la solicitud % ya fue resuelta', OLD.numero
              USING ERRCODE = 'check_violation';
          END IF;
          IF (NEW.id, NEW.numero, NEW.tipo, NEW.origen, NEW.entidad, NEW.entidad_id, NEW.motivo,
              NEW.solicitante_id, NEW.creada_en, NEW.solicitud_vinculada_id,
              NEW.propuesta_version_id)
             IS DISTINCT FROM
             (OLD.id, OLD.numero, OLD.tipo, OLD.origen, OLD.entidad, OLD.entidad_id, OLD.motivo,
              OLD.solicitante_id, OLD.creada_en, OLD.solicitud_vinculada_id,
              OLD.propuesta_version_id) THEN
            RAISE EXCEPTION 'una solicitud enviada no se modifica'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE app.alerta_th (
          id            uuid         PRIMARY KEY,
          tipo          varchar(24)  NOT NULL
                        CHECK (tipo IN ('USUARIO_AUSENTE', 'ARCHIVO_NO_RECIBIDO')),
          usuario_id    uuid         REFERENCES app.usuario (id),
          referencia    varchar(40)  NOT NULL,
          ejecucion_id  uuid         REFERENCES app.ejecucion_th (id),
          abierta_en    timestamptz  NOT NULL DEFAULT now(),
          cerrada_en    timestamptz,
          motivo_cierre varchar(200)
        )
        """
    )
    # Una alerta por periodo continuo (REQ-TH-05/06): única abierta por (tipo, referencia).
    op.execute("CREATE UNIQUE INDEX alerta_th_abierta_idx ON app.alerta_th (tipo, referencia) "
               "WHERE cerrada_en IS NULL")

    for codigo, asunto, cuerpo, canales in PLANTILLAS:
        sql = ("INSERT INTO ops.plantilla_notificacion (codigo, asunto, cuerpo, canales) "  # noqa: S608
               f"VALUES ('{codigo}', '{asunto}', '{cuerpo}', '{canales}')")
        op.execute(sql)
    op.execute(
        "INSERT INTO ops.parametro (clave, valor, tipo, descripcion) VALUES "
        "('th.zona_horaria', 'America/Bogota', 'TEXTO', 'Zona horaria para evaluar la llegada "
        "del archivo diario (DD-05).')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM ops.parametro WHERE clave = 'th.zona_horaria'")
    op.execute("DELETE FROM ops.plantilla_notificacion WHERE codigo LIKE 'TH_%'")
    op.execute("DROP TABLE app.alerta_th")
    op.execute("ALTER TABLE app.solicitud DROP COLUMN propuesta_version_id")
    op.execute("DROP TABLE app.propuesta_th_version")
    op.execute("DROP TABLE app.propuesta_th")
    op.execute("DROP TABLE app.resultado_fila_th")
    op.execute("DROP TABLE app.ejecucion_th")
