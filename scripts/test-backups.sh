#!/usr/bin/env bash
# Prueba de respaldos en el ambiente de pruebas (criterios 1–4 de FASE-10):
#  - rotación 7/4/3 con 100 días simulados (FAKE_DATE);
#  - registro en ops.registro_respaldo y audit.evento;
#  - restauración: vuelve al estado respaldado y la cadena de auditoría queda íntegra;
#  - un checksum alterado impide restaurar.
set -uo pipefail
cd "$(dirname "$0")/.."
ARGS=(-p secureone_test -f docker-compose.yml -f docker-compose.test.yml)
dc() { docker compose "${ARGS[@]}" "$@"; }
q() { dc exec -T postgres sh -c "psql -tA -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -c \"$1\""; }
fail=0
check() { if [[ "$2" == "$3" ]]; then echo "OK   $1 ($3)"; else echo "FAIL $1 (esperado $2, obtenido $3)"; fail=1; fi; }

# Volumen EFÍMERO de pruebas (backups_test): se vacían solo los archivos de respaldo.
dc exec -T backup find /backups -type f \( -name '*.dump' -o -name '*.dump.sha256' \) -delete
# 100 días desde el 2026-01-01 (incluye 14 domingos y 4 días 1).
dc exec -T backup sh -c '
  for i in $(seq 0 99); do
    FAKE_DATE=$(date -d "@$(( $(date -d 2026-01-01 +%s) + i * 86400 ))" +%F) backup.sh daily >/dev/null || exit 1
  done'
check "rotación diarios"   7 "$(dc exec -T backup sh -c 'ls /backups/daily/*.dump | wc -l' | tr -d ' ')"
check "rotación semanales" 4 "$(dc exec -T backup sh -c 'ls /backups/weekly/*.dump | wc -l' | tr -d ' ')"
check "rotación mensuales" 3 "$(dc exec -T backup sh -c 'ls /backups/monthly/*.dump | wc -l' | tr -d ' ')"
check "últimos diarios"    "2026-04-04.dump 2026-04-10.dump" \
  "$(dc exec -T backup sh -c 'ls /backups/daily | grep dump$ | sed -n "1p;7p" | xargs')"
check "mensuales vigentes" "2026-02.dump 2026-03.dump 2026-04.dump" \
  "$(dc exec -T backup sh -c 'ls /backups/monthly | grep dump$ | xargs')"
check "checksums presentes" 0 "$(dc exec -T backup sh -c 'for f in /backups/*/*.dump; do [ -f "$f.sha256" ] || echo x; done | wc -l' | tr -d ' ')"
check "registro respaldos (100 días simulados)" 100 "$(q "SELECT count(*) FROM ops.registro_respaldo WHERE tipo='DIARIO' AND resultado='EXITO' AND archivo BETWEEN '/backups/daily/2026-01-01' AND '/backups/daily/2026-04-11'")"
check "auditoría OPS_BACKUP_CREATED >= 118" t "$(q "SELECT count(*) >= 118 FROM audit.evento WHERE accion='OPS_BACKUP_CREATED'")"

# Restauración
q "INSERT INTO app.gerencia (codigo, nombre) VALUES ('RESTORE-A', 'Antes del respaldo')" >/dev/null
dc exec -T backup backup.sh manual prueba-restauracion >/dev/null
DUMP=$(dc exec -T backup sh -c 'ls -1 /backups/manual/*prueba-restauracion.dump | tail -1' | tr -d '\r')
q "INSERT INTO app.gerencia (codigo, nombre) VALUES ('RESTORE-B', 'Después del respaldo')" >/dev/null

# Checksum alterado → no restaura
# Se conserva el checksum original y se altera el CONTENIDO (no coincide con certeza).
dc exec -T backup sh -c "cp $DUMP /backups/manual/alterado.dump && printf 'X' >> /backups/manual/alterado.dump && sed 's/  .*/  alterado.dump/' $DUMP.sha256 > /backups/manual/alterado.dump.sha256"
dc exec -T backup restore.sh /backups/manual/alterado.dump --yes >/dev/null 2>&1
check "checksum alterado rechazado (rc)" 3 "$?"
check "sin restaurar tras rechazo" 1 "$(q "SELECT count(*) FROM app.gerencia WHERE codigo='RESTORE-B'")"

YES=1 COMPOSE_ARGS="${ARGS[*]}" ./scripts/restore.sh "$DUMP" >"${RESTORE_LOG:=$(mktemp)}" 2>&1
rc=$?
check "restauración (rc)" 0 "$rc"
check "dato previo presente" 1 "$(q "SELECT count(*) FROM app.gerencia WHERE codigo='RESTORE-A'")"
check "dato posterior ausente" 0 "$(q "SELECT count(*) FROM app.gerencia WHERE codigo='RESTORE-B'")"
check "cadena de auditoría íntegra" 1 "$(grep -c "íntegra" "$RESTORE_LOG")"
check "restauración registrada" 1 "$(q "SELECT count(*) FROM ops.registro_respaldo WHERE tipo='RESTAURACION'")"
check "restauración auditada" 1 "$(q "SELECT count(*) FROM audit.evento WHERE accion='OPS_RESTORE_EXECUTED'")"
check "backend healthy tras restaurar" healthy "$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q backend)")"
exit $fail
