"""IAM: roles, permisos, módulos, asignaciones, dominios y catálogos organizacionales.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10

Requisitos: REQ-IAM-01..07, 10..14, REQ-USER-02, REQ-USER-06, REQ-TH-13 (modelo).
Decisiones: PD-06 (APROBADO). Catálogo de permisos y módulos iniciales: PROPUESTOS (REQ-IAM-17).
Catálogos organizacionales: SIN DATOS; solo se cargan desde TH (PD-09 pendiente).
Sin campo Empresa. Sin borrado físico: asociaciones con estado.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIAS = ("CONSULTA", "CREACION", "EDICION", "ELIMINACION", "APROBACION", "EXPORTACION")

# Catálogo PROPUESTO (docs/especificaciones/ESP-ADM-IAM.md §5).
ADM_PERMISOS: dict[str, tuple[str, ...]] = {
    "USUARIO": ("CONSULTA", "CREACION", "EDICION", "ELIMINACION", "EXPORTACION"),
    "PERFIL": ("CONSULTA", "CREACION", "EDICION", "ELIMINACION"),
    "ROL": ("CONSULTA", "CREACION", "EDICION", "ELIMINACION"),
    "PERMISO": ("CONSULTA", "CREACION", "EDICION", "ELIMINACION"),
    "MODULO": ("CONSULTA", "CREACION", "EDICION", "ELIMINACION"),
    "DOMINIO": ("CONSULTA", "CREACION", "EDICION", "ELIMINACION"),
    "SOLICITUD": ("CONSULTA", "CREACION", "APROBACION"),
    "AUDITORIA": ("CONSULTA", "EXPORTACION"),
    "ERROR": ("CONSULTA", "EDICION"),
    "NOTIFICACION": ("CONSULTA",),
    "TH": ("CONSULTA", "CREACION"),
    "PARAMETRO": ("CONSULTA", "EDICION"),
    "ORG": ("CONSULTA",),
}


def _estado(name: str = "estado") -> str:
    return (f"{name} varchar(10) NOT NULL DEFAULT 'ACTIVO' "
            f"CHECK ({name} IN ('ACTIVO', 'INACTIVO'))")


def upgrade() -> None:
    cats = ", ".join(f"'{c}'" for c in CATEGORIAS)

    # ------------------------------------------------------------------ módulos
    op.execute(
        f"""
        CREATE TABLE app.modulo (
          id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          codigo          varchar(16)  NOT NULL UNIQUE CHECK (codigo ~ '^[A-Z]{{2,16}}$'),
          nombre          varchar(100) NOT NULL,
          descripcion     text,
          {_estado()},
          orden           integer      NOT NULL CHECK (orden > 0),
          ruta_frontend   varchar(100) NOT NULL,
          es_sistema      boolean      NOT NULL DEFAULT false,
          creado_en       timestamptz  NOT NULL DEFAULT now(),
          modificado_en   timestamptz,
          inhabilitado_en timestamptz,
          CONSTRAINT modulo_orden_key UNIQUE (orden) DEFERRABLE INITIALLY IMMEDIATE
        )
        """
    )
    op.execute(
        "INSERT INTO app.modulo (codigo, nombre, descripcion, orden, ruta_frontend, es_sistema) "
        "VALUES ('ADM', 'Administración', 'Usuarios, perfiles, roles, permisos, módulos, "
        "solicitudes, auditoría e integración TH.', 1, '/administracion', true), "
        "('IND', 'Indicium Insight', 'Gestión de indicadores KPI/KGI. Reglas de negocio "
        "aplazadas (D-IND-001).', 2, '/indicium', false)"
    )

    # ------------------------------------------------------------------ roles y permisos
    op.execute(
        f"""
        CREATE TABLE app.rol (
          id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          codigo          varchar(40)  NOT NULL UNIQUE CHECK (codigo ~ '^[A-Z][A-Z0-9_]{{1,39}}$'),
          nombre          varchar(100) NOT NULL,
          descripcion     text,
          {_estado()},
          es_sistema      boolean      NOT NULL DEFAULT false,
          creado_en       timestamptz  NOT NULL DEFAULT now(),
          modificado_en   timestamptz,
          inhabilitado_en timestamptz
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE app.permiso (
          id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          codigo          varchar(80)  NOT NULL UNIQUE,
          nombre          varchar(150) NOT NULL,
          descripcion     text,
          modulo_id       uuid         NOT NULL REFERENCES app.modulo (id),
          categoria       varchar(12)  NOT NULL CHECK (categoria IN ({cats})),
          {_estado()},
          es_sistema      boolean      NOT NULL DEFAULT false,
          creado_en       timestamptz  NOT NULL DEFAULT now(),
          modificado_en   timestamptz,
          inhabilitado_en timestamptz,
          CHECK (codigo ~ '^[A-Z]{{2,16}}\\.[A-Z][A-Z0-9_]{{1,40}}\\.[A-Z]+$'),
          CHECK (split_part(codigo, '.', 3) = categoria)
        )
        """
    )
    # El prefijo del código debe ser el módulo del permiso.
    op.execute(
        """
        CREATE FUNCTION app.validar_permiso_modulo() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF split_part(NEW.codigo, '.', 1)
             <> (SELECT codigo FROM app.modulo WHERE id = NEW.modulo_id) THEN
            RAISE EXCEPTION 'el prefijo del permiso debe ser el código de su módulo'
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER permiso_modulo BEFORE INSERT OR UPDATE OF codigo, modulo_id "
        "ON app.permiso FOR EACH ROW EXECUTE FUNCTION app.validar_permiso_modulo()"
    )

    for table, left, right in (
        ("perfil_rol", "perfil", "rol"),
        ("rol_permiso", "rol", "permiso"),
        ("usuario_modulo", "usuario", "modulo"),
    ):
        op.execute(
            f"""
            CREATE TABLE app.{table} (
              id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
              {left}_id       uuid        NOT NULL REFERENCES app.{left} (id),
              {right}_id      uuid        NOT NULL REFERENCES app.{right} (id),
              {_estado()},
              asignado_en     timestamptz NOT NULL DEFAULT now(),
              asignado_por    uuid,
              inhabilitado_en timestamptz,
              UNIQUE ({left}_id, {right}_id)
            )
            """
        )
        op.execute(f"CREATE INDEX {table}_{right}_idx ON app.{table} ({right}_id)")

    # ------------------------------------------------------------------ dominios (informativos)
    op.execute(
        f"""
        CREATE TABLE app.dominio (
          id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          codigo          varchar(40)  NOT NULL UNIQUE,
          nombre          varchar(150) NOT NULL,
          descripcion     text,
          modulo_id       uuid         REFERENCES app.modulo (id),
          {_estado()},
          creado_en       timestamptz  NOT NULL DEFAULT now(),
          modificado_en   timestamptz,
          inhabilitado_en timestamptz
        )
        """
    )

    # ------------------------------------------------------------------ catálogos organizacionales
    op.execute(
        f"""
        CREATE TABLE app.gerencia (
          id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          codigo          varchar(40)  NOT NULL UNIQUE,
          nombre          varchar(150) NOT NULL,
          {_estado()},
          creado_en       timestamptz  NOT NULL DEFAULT now(),
          modificado_en   timestamptz,
          inhabilitado_en timestamptz
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE app.area (
          id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          codigo          varchar(40)  NOT NULL UNIQUE,
          nombre          varchar(150) NOT NULL,
          gerencia_id     uuid         NOT NULL REFERENCES app.gerencia (id),
          {_estado()},
          creado_en       timestamptz  NOT NULL DEFAULT now(),
          modificado_en   timestamptz,
          inhabilitado_en timestamptz,
          UNIQUE (id, gerencia_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE app.cargo (
          id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
          codigo_cargo    integer      NOT NULL UNIQUE CHECK (codigo_cargo > 0),
          nombre          varchar(150) NOT NULL,
          {_estado()},
          creado_en       timestamptz  NOT NULL DEFAULT now(),
          modificado_en   timestamptz,
          inhabilitado_en timestamptz
        )
        """
    )
    op.execute(
        """
        ALTER TABLE app.usuario
          ADD COLUMN gerencia_id uuid REFERENCES app.gerencia (id),
          ADD COLUMN area_id     uuid,
          ADD COLUMN cargo_id    uuid REFERENCES app.cargo (id),
          ADD CONSTRAINT usuario_area_gerencia_fkey
            FOREIGN KEY (area_id, gerencia_id) REFERENCES app.area (id, gerencia_id),
          ADD CONSTRAINT usuario_area_requiere_gerencia
            CHECK (area_id IS NULL OR gerencia_id IS NOT NULL)
        """
    )

    # ------------------------------------------------------------------ permisos efectivos
    op.execute(
        """
        CREATE VIEW app.v_permiso_efectivo AS
        SELECT DISTINCT u.id AS usuario_id, p.codigo AS permiso, m.codigo AS modulo
          FROM app.usuario u
          JOIN app.perfil pf        ON pf.id = u.perfil_id AND pf.estado = 'ACTIVO'
          JOIN app.perfil_rol pr    ON pr.perfil_id = pf.id AND pr.estado = 'ACTIVO'
          JOIN app.rol r            ON r.id = pr.rol_id AND r.estado = 'ACTIVO'
          JOIN app.rol_permiso rp   ON rp.rol_id = r.id AND rp.estado = 'ACTIVO'
          JOIN app.permiso p        ON p.id = rp.permiso_id AND p.estado = 'ACTIVO'
          JOIN app.modulo m         ON m.id = p.modulo_id AND m.estado = 'ACTIVO'
          JOIN app.usuario_modulo um ON um.usuario_id = u.id AND um.modulo_id = m.id
                                    AND um.estado = 'ACTIVO'
         WHERE u.estado = 'ACTIVO'
        """
    )

    # ------------------------------------------------------------------ datos iniciales
    values = []
    for recurso, categorias in ADM_PERMISOS.items():
        for cat in categorias:
            values.append(
                f"('ADM.{recurso}.{cat}', '{recurso.capitalize()}: {cat.lower()}', '{cat}')"
            )
    # Valores fijos de esta migración (catálogo estático), no entrada externa.
    insert_sql = (
        "INSERT INTO app.permiso (codigo, nombre, categoria, modulo_id, es_sistema) "  # noqa: S608
        "SELECT v.codigo, v.nombre, v.categoria, m.id, true FROM (VALUES "
        + ", ".join(values)
        + ") AS v(codigo, nombre, categoria) CROSS JOIN app.modulo m WHERE m.codigo = 'ADM'"
    )
    op.execute(insert_sql)
    op.execute(
        "INSERT INTO app.rol (codigo, nombre, descripcion, es_sistema) VALUES "
        "('ADMINISTRADOR_TOTAL', 'Administración total', "
        "'Rol de sistema con todos los permisos ADM.* (PD-06).', true)"
    )
    op.execute(
        "INSERT INTO app.rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM app.rol r "
        "CROSS JOIN app.permiso p WHERE r.codigo = 'ADMINISTRADOR_TOTAL' "
        "AND p.codigo LIKE 'ADM.%'"
    )
    op.execute(
        "INSERT INTO app.perfil_rol (perfil_id, rol_id) SELECT pf.id, r.id FROM app.perfil pf "
        "CROSS JOIN app.rol r WHERE pf.codigo = 'ADMINISTRADOR' "
        "AND r.codigo = 'ADMINISTRADOR_TOTAL'"
    )
    # Administradores ya existentes: módulo ADM asignado.
    op.execute(
        "INSERT INTO app.usuario_modulo (usuario_id, modulo_id) SELECT u.id, m.id "
        "FROM app.usuario u JOIN app.perfil pf ON pf.id = u.perfil_id "
        "CROSS JOIN app.modulo m WHERE pf.codigo = 'ADMINISTRADOR' AND m.codigo = 'ADM'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW app.v_permiso_efectivo")
    op.execute(
        "ALTER TABLE app.usuario DROP CONSTRAINT usuario_area_requiere_gerencia, "
        "DROP CONSTRAINT usuario_area_gerencia_fkey, DROP COLUMN cargo_id, "
        "DROP COLUMN area_id, DROP COLUMN gerencia_id"
    )
    for t in ("cargo", "area", "gerencia", "dominio", "usuario_modulo", "rol_permiso",
              "perfil_rol", "permiso", "rol", "modulo"):
        op.execute(f"DROP TABLE app.{t}")
    op.execute("DROP FUNCTION app.validar_permiso_modulo()")
