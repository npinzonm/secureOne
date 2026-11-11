#!/usr/bin/env bash
# Restaura un respaldo en el stack (base por defecto; COMPOSE_ARGS para otro proyecto).
#   ./scripts/restore.sh backups/daily/2026-11-11.dump
# Detiene backend/worker/nginx, verifica el checksum, respalda el estado actual, restaura,
# vuelve a levantar (migrate deja la BD en head) y verifica la cadena de auditoría.
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${1:?uso: scripts/restore.sh <ruta al .dump dentro de la carpeta de respaldos>}"
read -r -a CARGS <<< "${COMPOSE_ARGS:-}"
dc() { docker compose ${CARGS[@]+"${CARGS[@]}"} "$@"; }

# Ruta del archivo dentro del contenedor (/backups/...).
REL="${FILE#*backups/}"
[[ "$REL" == "$FILE" ]] && REL="${FILE#/backups/}"
TARGET="/backups/${REL#/}"

if [[ "${YES:-}" != "1" ]]; then
  read -r -p "La restauración REEMPLAZA la base de datos actual con $TARGET. Escriba RESTAURAR: " ans
  [[ "$ans" == "RESTAURAR" ]] || { echo "Cancelado."; exit 1; }
fi
dc stop nginx backend worker >/dev/null
dc exec -T backup restore.sh "$TARGET" --yes
dc up -d --wait >/dev/null
dc exec -T backend python -m app.cli audit-verify
