#!/bin/sh
# Respaldos de SecureOne (REQ-RNF-08 / M §15; PD-26).
#
#   backup.sh daemon            # bucle: respaldo diario a BACKUP_HOUR (zona TZ)
#   backup.sh daily             # respaldo diario + copias semanal/mensual + rotación
#   backup.sh manual [etiqueta] # respaldo adicional (p. ej. antes de actualizar)
#
# Retención (M §15.2): 7 diarios, 4 semanales (domingo), 3 mensuales (día 1).
# Cada archivo .dump lleva su .sha256. Cada operación se registra en ops.registro_respaldo
# y en audit.evento. FAKE_DATE=AAAA-MM-DD solo existe para las pruebas de rotación.
set -eu

BASE=/backups
KEEP_DAILY=7
KEEP_WEEKLY=4
KEEP_MONTHLY=3
export PGHOST="${PGHOST:-postgres}" PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD" PGDATABASE="$POSTGRES_DB"

log() { echo "{\"ts\":\"$(date -u +%FT%TZ)\",\"component\":\"backup\",\"msg\":\"$*\"}"; }

register() { # tipo archivo sha tamano resultado inicio detalle
  psql -v ON_ERROR_STOP=1 -q -v tipo="$1" -v archivo="$2" -v sha="$3" -v tamano="$4" \
       -v resultado="$5" -v inicio="$6" -v detalle="$7" <<'SQL'
INSERT INTO ops.registro_respaldo (tipo, archivo, sha256, tamano, inicio, resultado, detalle)
VALUES (:'tipo', :'archivo', NULLIF(:'sha', ''), NULLIF(:'tamano', '')::bigint,
        :'inicio'::timestamptz, :'resultado', NULLIF(:'detalle', ''));
INSERT INTO audit.evento (id, actor_tipo, categoria, modulo, accion, resultado, entidad, entidad_id, detalle)
VALUES (gen_random_uuid(), 'SISTEMA', 'OPERACION', 'ADM',
        CASE WHEN :'tipo' = 'RESTAURACION' THEN 'OPS_RESTORE_EXECUTED' ELSE 'OPS_BACKUP_CREATED' END,
        CASE WHEN :'resultado' = 'EXITO' THEN 'EXITO' ELSE 'FALLO' END,
        'respaldo', :'archivo',
        jsonb_build_object('tipo', :'tipo', 'sha256', NULLIF(:'sha', ''), 'tamano', NULLIF(:'tamano', '')));
SQL
}

dump() { # tipo ruta
  start=$(date -u +%FT%TZ)
  if pg_dump -Fc -f "$2.tmp"; then
    mv "$2.tmp" "$2"
    sha=$(sha256sum "$2" | cut -d' ' -f1)
    echo "$sha  $(basename "$2")" > "$2.sha256"
    register "$1" "$2" "$sha" "$(stat -c %s "$2")" EXITO "$start" ""
    log "respaldo $1 creado: $2"
  else
    rm -f "$2.tmp"
    register "$1" "$2" "" "" FALLO "$start" "pg_dump falló" || true
    log "ERROR: respaldo $1 falló"
    return 1
  fi
}

copy_as() { # tipo origen destino
  cp "$2" "$3"
  sha=$(cut -d' ' -f1 < "$2.sha256")
  echo "$sha  $(basename "$3")" > "$3.sha256"
  register "$1" "$3" "$sha" "$(stat -c %s "$3")" EXITO "$(date -u +%FT%TZ)" "copia de $(basename "$2")"
}

rotate() { # directorio conservar
  # Los nombres AAAA-MM-DD / AAAA-Www / AAAA-MM ordenan cronológicamente.
  ls -1 "$1"/*.dump 2>/dev/null | sort -r | tail -n +"$(($2 + 1))" | while read -r old; do
    rm -f "$old" "$old.sha256"
    log "rotación: eliminado $(basename "$old")"
  done
}

daily() {
  day="${FAKE_DATE:-$(date +%F)}"
  mkdir -p "$BASE/daily" "$BASE/weekly" "$BASE/monthly"
  file="$BASE/daily/$day.dump"
  dump DIARIO "$file"
  if [ "$(date -d "$day" +%u)" = "7" ]; then
    copy_as SEMANAL "$file" "$BASE/weekly/$(date -d "$day" +%G-W%V).dump"
  fi
  if [ "$(date -d "$day" +%d)" = "01" ]; then
    copy_as MENSUAL "$file" "$BASE/monthly/$(date -d "$day" +%Y-%m).dump"
  fi
  rotate "$BASE/daily" "$KEEP_DAILY"
  rotate "$BASE/weekly" "$KEEP_WEEKLY"
  rotate "$BASE/monthly" "$KEEP_MONTHLY"
}

manual() {
  mkdir -p "$BASE/manual"
  label=$(echo "${1:-manual}" | tr -cd 'A-Za-z0-9_-' | cut -c1-40)
  dump MANUAL "$BASE/manual/$(date +%Y%m%dT%H%M%S)-${label:-manual}.dump"
}

daemon() {
  hour="${BACKUP_HOUR:-02}"
  log "servicio de respaldos iniciado (diario a las ${hour}:00, TZ=${TZ:-UTC})"
  while true; do
    date +%s > /tmp/backup-alive
    today=$(date +%F)
    if [ "$(date +%H)" -ge "$hour" ] && [ ! -f "$BASE/daily/$today.dump" ]; then
      daily || log "ERROR: el respaldo diario falló; se reintentará en el próximo ciclo"
    fi
    sleep 60
  done
}

case "${1:-}" in
  daemon) daemon ;;
  daily) daily ;;
  manual) shift; manual "${1:-manual}" ;;
  *) echo "uso: backup.sh daemon|daily|manual [etiqueta]" >&2; exit 2 ;;
esac
