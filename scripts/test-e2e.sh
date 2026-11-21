#!/usr/bin/env bash
# E2E de navegador (Playwright en contenedor) contra el ambiente de PRUEBAS efímero.
# Prepara datos de prueba por la API con credenciales aleatorias de un solo uso (nunca se
# imprimen) y ejecuta frontend/e2e en la imagen oficial de Playwright.
set -euo pipefail
cd "$(dirname "$0")/.."
ARGS=(-p secureone_test -f docker-compose.yml -f docker-compose.test.yml)
dc() { docker compose "${ARGS[@]}" "$@"; }
B="http://127.0.0.1:${TEST_HTTP_PORT:-8081}/api/v1"
PW_VERSION=1.64.1

dc down -v >/dev/null 2>&1 || true
dc up -d --build --wait >/dev/null
gen() { echo "E2e#$(openssl rand -hex 6)Az9"; }
json() { python3 -c "import json,sys;print(json.load(sys.stdin)$1)"; }
temp_of() { sed -n 's/^    \(.*\)$/\1/p' | head -1; }

ADMIN=e1a2d3m4; ADMIN_PWD=$(gen)
T1=$(dc exec -T backend python -m app.cli bootstrap-admin --usuario-red $ADMIN --identificacion E2E-ADM \
  --nombre Admin --primer-apellido E2E --segundo-apellido "" --correo e2e.admin@example.org | temp_of)
TEMP_USER=e5t6m7p8
TEMP_PWD=$(dc exec -T backend python -m app.cli bootstrap-admin --usuario-red $TEMP_USER --identificacion E2E-TMP \
  --nombre Temporal --primer-apellido E2E --segundo-apellido "" --correo e2e.tmp@example.org | temp_of)

tok=$(curl -sf -H 'Content-Type: application/json' -d "{\"usuario_red\":\"$ADMIN\",\"password\":\"$T1\"}" $B/auth/login | json "['access_token']")
curl -sf -o /dev/null -H "Authorization: Bearer $tok" -H 'Content-Type: application/json' \
  -d "{\"current_password\":\"$T1\",\"new_password\":\"$ADMIN_PWD\"}" $B/auth/password/change
TOK=$(curl -sf -H 'Content-Type: application/json' -d "{\"usuario_red\":\"$ADMIN\",\"password\":\"$ADMIN_PWD\"}" $B/auth/login | json "['access_token']")
curl -sf -o /dev/null -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"codigo":"ANALISTA_E2E","nombre":"Analista E2E"}' $B/admin/profiles
PLANT=$(mktemp -d)/planta_activa.xlsx
dc exec -T backend python -c "
from openpyxl import Workbook; import sys, io
wb=Workbook(); ws=wb.active
ws.append(['IDENTIFICACION','NOMBRES','PRIMER_APELLIDO','CORREO','USUARIO_RED','CODIGO_GERENCIA','GERENCIA','CODIGO_AREA','AREA','CODIGO_CARGO','CARGO'])
ws.append(['CC-2001','Laura','Prueba','laura@example.org','l1a2u3r4','GSI','Gerencia SI','ACIB','Ciberseguridad',400,'Analista'])
b=io.BytesIO(); wb.save(b); sys.stdout.buffer.write(b.getvalue())" > "$PLANT"
curl -sf -o /dev/null -H "Authorization: Bearer $TOK" -F tipo=ACTIVA -F "archivo=@$PLANT" $B/admin/th/files
for _ in $(seq 1 20); do
  st=$(curl -sf -H "Authorization: Bearer $TOK" $B/admin/th/executions | json "[0]['estado']")
  [[ "$st" != "PENDIENTE" ]] && break; sleep 1
done
echo "planta TH: $st"
curl -sf -o /dev/null -X POST -H "Authorization: Bearer $TOK" $B/auth/logout

docker run --rm --network secureone_test_edge \
  -e E2E_USER=$ADMIN -e E2E_PASSWORD="$ADMIN_PWD" -e E2E_TEMP_USER=$TEMP_USER -e E2E_TEMP_PASSWORD="$TEMP_PWD" \
  -e E2E_NEW_PASSWORD="$(gen)" -e CI=1 \
  -v "$PWD/frontend:/src:ro" mcr.microsoft.com/playwright:v${PW_VERSION}-noble \
  bash -c "mkdir -p /work && cd /work && cp -r /src/e2e /src/playwright.config.ts . \
    && npm init -y >/dev/null && npm i --no-save --no-audit --no-fund @playwright/test@${PW_VERSION} >/dev/null \
    && npx playwright test"
