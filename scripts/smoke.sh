#!/usr/bin/env bash
# Smoke test de la Fase 1: valida los criterios de aceptación 2–4 contra el stack levantado.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${HTTP_PORT:-$(grep -E '^HTTP_PORT=' .env 2>/dev/null | cut -d= -f2 || true)}"
PORT="${PORT:-8080}"
BASE="http://127.0.0.1:${PORT}"
read -r -a CARGS <<< "${COMPOSE_ARGS:-}"
fail=0

check() { # nombre esperado obtenido
  if [[ "$2" == "$3" ]]; then echo "OK   $1 ($3)"; else echo "FAIL $1 (esperado $2, obtenido $3)"; fail=1; fi
}
code() { curl -s -o /dev/null -w '%{http_code}' "$1"; }

check "frontend /"                  200 "$(code "$BASE/")"
check "api live"                    200 "$(code "$BASE/api/v1/health/live")"
check "api ready bloqueado externo" 404 "$(code "$BASE/api/v1/health/ready")"

internal=$(docker compose ${CARGS[@]+"${CARGS[@]}"} exec -T backend python -c "
import urllib.request as u
try:
    print(u.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=5).status)
except Exception as e:
    print(getattr(e, 'code', 'ERR'))")
check "api ready interno"           200 "$internal"

hdr=$(curl -sI "$BASE/" | tr -d '\r' | grep -ci '^x-content-type-options: nosniff' || true)
check "cabecera nosniff"            1 "$hdr"

exit $fail
