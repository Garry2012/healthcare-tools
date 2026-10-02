# Front-desk MCP adapter. Everything reads the repository-root .env (copy .env.example first).
SHELL := /bin/bash
COMPOSE := docker compose -f deploy/docker-compose.yml --env-file .env
MCP := services/mcp

.PHONY: up up-mcp down test test-fast test-e2e lint build schema agent-instructions demo bench logs

up: ## Start the adapter against the two local development stubs (profiles mcp + stubs)
	$(COMPOSE) --profile stubs up -d --build --wait

up-mcp: ## Start only the adapter, pointed at the owner services configured in .env
	$(COMPOSE) --profile mcp up -d --build --wait mcp

down: ## Stop everything
	$(COMPOSE) --profile stubs --profile mcp down

test: ## Everything a reviewer needs on a clean checkout: lint, unit, stub-backed e2e, build (scripts/test.sh)
	./scripts/test.sh

test-fast: ## Seconds, no processes: lint and the hermetic suites
	cd $(MCP) && uv run ruff check . ../../deploy && uv run pytest tests -q -m "not e2e and not external"

test-e2e: ## Real processes over TCP: stubs + adapter, release smoke, full journey
	cd $(MCP) && uv run pytest tests -q -m e2e

lint:
	cd $(MCP) && uv run ruff check . ../../deploy

build: ## Build the production image (stubs and fixtures are not in it)
	docker build -t frontdesk-mcp:dev $(MCP)

schema: ## Print the pinned tool surface (compare with tests/contracts/mcp-tools.snapshot.json)
	@cd $(MCP) && eval "$$(../../scripts/rollout-env.sh ../../rollouts/$${PROVIDER_ID:-demo-hospital})" && \
	  ENV=development OPS_BASE_URL=http://127.0.0.1:8200/api/v1 uv run frontdesk-mcp schema

agent-instructions: ## Print versioned rules for the voice team's Agent(instructions=...)
	@cd $(MCP) && eval "$$(../../scripts/rollout-env.sh ../../rollouts/$${PROVIDER_ID:-demo-hospital})" && \
	  ENV=development OPS_BASE_URL=http://127.0.0.1:8200/api/v1 uv run frontdesk-mcp agent-instructions

demo: ## In-process walk-through of the four tools against the stubs (dev/demo.py)
	cd $(MCP) && uv run python dev/demo.py

bench: ## Tool round-trip latency: in-process stubs by default; `eval "$$(scripts/env.sh mock|live)"` first for a real host
	cd $(MCP) && uv run python dev/bench.py

logs:
	$(COMPOSE) --profile stubs logs -f
