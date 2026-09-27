# Front-desk MVP. Everything reads the repository-root .env (copy .env.example first).
SHELL := /bin/bash
COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env

.PHONY: up down migrate seed seed-reset rollout-validate rollout-apply test test-fast demo lint logs build

up: ## Start postgres, run migrations, start api and mcp (dev profile)
	$(COMPOSE) --profile dev up -d --build --wait api mcp

down: ## Stop the dev stack (data volume kept)
	$(COMPOSE) --profile dev --profile test down

migrate: ## Alembic upgrade head as the owner role
	$(COMPOSE) --profile dev run --rm migrate

rollout-validate: ## Offline check of rollouts/$(PROVIDER_ID) (settings, data, dialogues); ROLLOUT=<dir> for another
	cd services/api && uv run frontdesk-api rollout validate $(abspath $(or $(ROLLOUT),rollouts/$(or $(PROVIDER_ID),demo-hospital)))

rollout-apply: ## Write the running stack's rollout (domain baseline + its data) to its database
	$(COMPOSE) --profile dev exec api frontdesk-api rollout apply

seed: ## Apply the demo rollout and its dated demo scenario (idempotent; refused in production)
	$(COMPOSE) --profile dev exec api frontdesk-api seed

seed-reset: ## DESTRUCTIVE: empty every table in the dev database, then seed
	$(COMPOSE) --profile dev exec api frontdesk-api seed --reset

test: ## Everything (L4): unit + integration + contract + MCP e2e + schemathesis, on a throwaway postgres
	./scripts/test.sh

test-fast: ## Seconds, no database (L1): lint, architecture contracts, API unit + spec, MCP unit
	cd services/api && uv run ruff check . && uv run lint-imports && uv run pytest tests/unit tests/contract/test_openapi_matches_spec.py -q
	cd services/mcp && uv run ruff check . ../../deploy && uv run pytest tests -q -m "not e2e"

demo: ## Kannada search → book → list → reschedule → cancel against the dev stack
	./scripts/demo.sh

lint: ## ruff on both services, and the API's architecture contracts
	cd services/api && uv run ruff check . && uv run lint-imports
	cd services/mcp && uv run ruff check . ../../deploy

build: ## Build both images
	docker build -t frontdesk-api:dev services/api
	docker build -t frontdesk-mcp:dev services/mcp

logs:
	$(COMPOSE) --profile dev logs -f api mcp
