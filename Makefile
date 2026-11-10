# Atajos de operación SecureOne. Requiere Docker Compose v2.
DC      := docker compose
DC_DEV  := docker compose -f docker-compose.yml -f docker-compose.dev.yml
DC_TEST := docker compose -p secureone_test -f docker-compose.yml -f docker-compose.test.yml

.PHONY: env up up-dev down down-dev logs ps health lint test test-stack test-stack-down

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

test:           ## Pruebas del backend (en contenedor, sin dependencias externas)
	$(DC_TEST) run --rm --no-deps backend pytest

test-stack:     ## Levanta el ambiente de pruebas aislado y ejecuta el smoke test
	$(DC_TEST) up -d --build --wait
	HTTP_PORT=$${TEST_HTTP_PORT:-8081} COMPOSE_ARGS="-p secureone_test -f docker-compose.yml -f docker-compose.test.yml" ./scripts/smoke.sh

test-stack-down: ## Detiene el ambiente de pruebas y borra sus datos efímeros
	$(DC_TEST) down -v
