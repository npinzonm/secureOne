#!/usr/bin/env bash
# Genera .env a partir de .env.example con secretos aleatorios.
# No sobrescribe un .env existente. Los secretos no se imprimen.
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="${1:-.env}"
if [[ -e "$TARGET" ]]; then
  echo "$TARGET ya existe; no se modifica." >&2
  exit 0
fi
gen() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-40; }
umask 077
sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(gen)|" \
    -e "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$(gen)|" \
    .env.example > "$TARGET"
echo "Creado $TARGET con secretos aleatorios (permisos 600)."
