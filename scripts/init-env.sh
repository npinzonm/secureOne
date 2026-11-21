#!/usr/bin/env bash
# Genera .env a partir de .env.example con secretos aleatorios.
# - Si .env no existe, lo crea.
# - Si existe, NO modifica valores existentes: solo agrega las claves nuevas de .env.example
#   (con secreto aleatorio cuando corresponde). Los secretos nunca se imprimen.
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="${1:-.env}"
PLACEHOLDER="__GENERADO_POR_init-env.sh__"
gen() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-40; }
umask 077

if [[ ! -e "$TARGET" ]]; then
  : > "$TARGET"
  created=1
else
  created=0
fi

added=0
while IFS= read -r line || [[ -n "$line" ]]; do
  if [[ "$line" =~ ^([A-Z_][A-Z0-9_]*)=(.*)$ ]]; then
    key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
    if grep -qE "^${key}=" "$TARGET"; then
      continue
    fi
    [[ "$val" == "$PLACEHOLDER" ]] && val="$(gen)"
    printf '%s=%s\n' "$key" "$val" >> "$TARGET"
    added=$((added + 1))
  elif [[ $created -eq 1 ]]; then
    printf '%s\n' "$line" >> "$TARGET"
  fi
done < .env.example

chmod 600 "$TARGET"
if [[ $created -eq 1 ]]; then
  echo "Creado $TARGET con secretos aleatorios (permisos 600)."
elif [[ $added -gt 0 ]]; then
  echo "$TARGET existente: se agregaron $added clave(s) nueva(s); valores existentes sin cambios."
else
  echo "$TARGET ya está completo; no se modificó."
fi
