# Front-desk MVP. Everything reads the repository-root .env (copy .env.example first).
SHELL := /bin/bash
COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env

.PHONY: up down migrate seed seed-reset test demo lint logs build

up: ## Start postgres, run migrations, start api and mcp (dev profile)
	$(COMPOSE) --profile dev up -d --build --wait api mcp

down: ## Stop the dev stack (data volume kept)
	$(COMPOSE) --profile dev --profile test down

migrate: ## Alembic upgrade head as the owner role
	$(COMPOSE) --profile dev run --rm migrate

seed: ## Load synthetic demo data (idempotent)
	$(COMPOSE) --profile dev exec api healthcare-api seed

seed-reset: ## DESTRUCTIVE: empty every table in the dev database and reload the seed
	$(COMPOSE) --profile dev exec api healthcare-api seed --reset

test: ## Unit + integration + contract + MCP suites against a throwaway postgres
	./scripts/test.sh

demo: ## Kannada search → book → list → reschedule → cancel against the dev stack
	./scripts/demo.sh

lint: ## ruff on both services
	cd services/api && uv run ruff check src tests
	cd services/mcp && uv run ruff check src tests

build: ## Build both images
	docker build -t healthcare-api:dev services/api
	docker build -t healthcare-mcp:dev services/mcp

logs:
	$(COMPOSE) --profile dev logs -f api mcp
