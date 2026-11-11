# Atajos de operación SecureOne. Requiere Docker Compose v2.
DC      := docker compose
DC_DEV  := docker compose -f docker-compose.yml -f docker-compose.dev.yml
DC_TEST := docker compose -p secureone_test -f docker-compose.yml -f docker-compose.test.yml

.PHONY: env up up-dev down down-dev logs ps health lint test test-int migrate audit-verify bootstrap-admin backup update restore test-backups test-e2e test-stack test-stack-down

env:            ## Genera .env con secretos aleatorios (no sobrescribe)
	./scripts/init-env.sh

up: env         ## Levanta el stack base
	$(DC) up -d --build --wait

up-dev: env     ## Levanta el stack de desarrollo (hot reload)
	$(DC_DEV) up -d --build --wait

down:           ## Detiene el stack (conserva volúmenes)
	$(DC) down

down-dev:
	$(DC_DEV) down

logs:
	$(DC) logs -f --tail=200

ps:
	$(DC) ps

health:         ## Verifica health checks a través de Nginx
	./scripts/smoke.sh

lint:           ## Ruff sobre el backend (en contenedor)
	$(DC_TEST) run --rm --no-deps backend ruff check app tests

test:           ## Pruebas unitarias/API del backend (en contenedor, sin dependencias externas)
	$(DC_TEST) run --rm --no-deps backend pytest -m "not integration"

test-int: env   ## Pruebas de integración contra PostgreSQL/Redis reales (ambiente test aislado)
	$(DC_TEST) run --rm backend pytest -m integration

migrate:        ## Aplica migraciones (rol owner) en el stack base
	$(DC) run --rm migrate

backup:         ## Respaldo MANUAL inmediato (además del diario automático): make backup LABEL=x
	$(DC) exec backup backup.sh manual $${LABEL:-manual}

update:         ## Actualizar: respaldo previo + reconstruir y levantar (aplica migraciones)
	$(DC) exec backup backup.sh manual pre-actualizacion
	$(DC) up -d --build --wait

restore:        ## Restaurar: make restore FILE=backups/daily/AAAA-MM-DD.dump
	./scripts/restore.sh $(FILE)

test-backups:   ## Prueba de rotación 7/4/3 y de restauración (ambiente de pruebas)
	$(DC_TEST) up -d --build --wait
	./scripts/test-backups.sh

test-e2e:       ## E2E de navegador (Playwright en contenedor) contra el ambiente de pruebas
	./scripts/test-e2e.sh

bootstrap-admin: ## Crea un administrador inicial (interactivo; máx. 2). Muestra la temporal una vez
	$(DC) exec backend python -m app.cli bootstrap-admin

audit-verify:   ## Verifica la cadena de hash de la auditoría
	$(DC) exec backend python -m app.cli audit-verify

test-stack:     ## Levanta el ambiente de pruebas aislado y ejecuta el smoke test
	$(DC_TEST) up -d --build --wait
	HTTP_PORT=$${TEST_HTTP_PORT:-8081} COMPOSE_ARGS="-p secureone_test -f docker-compose.yml -f docker-compose.test.yml" ./scripts/smoke.sh

test-stack-down: ## Detiene el ambiente de pruebas y borra sus datos efímeros
	$(DC_TEST) down -v
