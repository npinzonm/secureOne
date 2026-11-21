#!/bin/sh
# Restauración de un respaldo (REQ-RNF-08: "procedimiento de restauración probado").
#
#   restore.sh /backups/daily/2026-11-11.dump --yes
#
# 1. Verifica el SHA-256 (si no coincide, NO restaura).
# 2. Toma un respaldo de seguridad del estado actual (manual "pre-restauracion").
# 3. pg_restore --clean --if-exists (los triggers de auditoría se crean DESPUÉS de cargar los
#    datos, por lo que la cadena de hash se restaura tal cual).
# 4. Registra la restauración en ops.registro_respaldo y en audit.evento.
# El backend y el worker deben estar detenidos (lo hace scripts/restore.sh en el host).
set -eu
FILE="${1:-}"
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "ERROR: indique un archivo .dump existente" >&2; exit 2; }
[ "${2:-}" = "--yes" ] || { echo "ERROR: la restauración reemplaza la BD; confirme con --yes" >&2; exit 2; }
export PGHOST="${PGHOST:-postgres}" PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD" PGDATABASE="$POSTGRES_DB"

cd "$(dirname "$FILE")"
if ! sha256sum -c "$(basename "$FILE").sha256" >/dev/null 2>&1; then
  echo "ERROR: el checksum SHA-256 no coincide; el respaldo pudo alterarse. No se restaura." >&2
  exit 3
fi
echo "checksum verificado"
/usr/local/bin/backup.sh manual pre-restauracion
start=$(date -u +%FT%TZ)
pg_restore --clean --if-exists --exit-on-error -d "$POSTGRES_DB" "$FILE"
sha=$(cut -d' ' -f1 < "$(basename "$FILE").sha256")
psql -v ON_ERROR_STOP=1 -q -v archivo="$FILE" -v sha="$sha" -v inicio="$start" <<'SQL'
INSERT INTO ops.registro_respaldo (tipo, archivo, sha256, inicio, resultado, detalle)
VALUES ('RESTAURACION', :'archivo', :'sha', :'inicio'::timestamptz, 'EXITO', 'pg_restore --clean');
INSERT INTO audit.evento (id, actor_tipo, categoria, modulo, accion, resultado, entidad, entidad_id, detalle)
VALUES (gen_random_uuid(), 'SISTEMA', 'OPERACION', 'ADM', 'OPS_RESTORE_EXECUTED', 'EXITO',
        'respaldo', :'archivo', jsonb_build_object('sha256', :'sha'));
SQL
echo "restauración completada desde $FILE"
