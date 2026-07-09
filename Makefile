# Spidey — single entry point for every routine task.
# Windows users without make: each target is a thin wrapper; run the commands
# directly (see CONTRIBUTING.md).

COMPOSE      := docker compose --env-file .env -f deploy/compose/docker-compose.yml
COMPOSE_DEV  := $(COMPOSE) -f deploy/compose/docker-compose.dev.yml
UV           := uv

.PHONY: bootstrap dev dev-min down logs test test-unit test-integration lint \
        format typecheck security eval openapi docs clean

bootstrap: ## Install backend deps + git hooks
	cd backend && $(UV) sync --group dev
	cd backend && $(UV) run pre-commit install --install-hooks

dev: ## Start full stack (app services + observability profile)
	COMPOSE_PROFILES=obs SPIDEY_OTEL_COLLECTOR_ENDPOINT=http://otel-collector:4318 \
		$(COMPOSE_DEV) up -d --build --wait

dev-min: ## Start core services only (fast loop: pg, redis, qdrant, api, worker)
	$(COMPOSE_DEV) up -d --build --wait

down: ## Stop the stack (volumes preserved)
	COMPOSE_PROFILES=obs $(COMPOSE_DEV) down

logs: ## Tail all service logs
	COMPOSE_PROFILES=obs $(COMPOSE_DEV) logs -f --tail=100

test: ## All tests with coverage gate
	cd backend && $(UV) run pytest --cov=spidey --cov-report=term-missing --cov-fail-under=85

test-unit: ## Fast unit tests only (no services required)
	cd backend && $(UV) run pytest tests/unit tests/security -q

test-integration: ## Integration tests (require pg/redis reachable)
	cd backend && $(UV) run pytest tests/integration -q

lint: ## Ruff lint + format check + architecture contracts
	cd backend && $(UV) run ruff check .
	cd backend && $(UV) run ruff format --check .
	cd backend && $(UV) run lint-imports

format: ## Auto-fix lint + formatting
	cd backend && $(UV) run ruff check --fix .
	cd backend && $(UV) run ruff format .

typecheck: ## Pyright strict
	cd backend && $(UV) run pyright

security: ## Local security pass (bandit, semgrep rules, pip-audit; gitleaks runs in pre-commit)
	cd backend && $(UV) run bandit -r src -c pyproject.toml -ll
	cd backend && $(UV) run --with semgrep semgrep scan --config ../infra/policy/semgrep --error --metrics=off
	cd backend && $(UV) export --frozen --no-emit-project --format requirements.txt -o requirements-audit.txt \
		&& $(UV) run --with pip-audit pip-audit -r requirements-audit.txt --strict \
		&& rm requirements-audit.txt

eval: ## Run evaluation suites (TIER=t1|t2|t3, default t1)
	cd backend && $(UV) run python -m spidey.evaluation run --tier $(or $(TIER),t1) --check-baselines

openapi: ## Export the OpenAPI spec to docs/api/openapi.json
	cd backend && $(UV) run python ../scripts/export_openapi.py ../docs/api/openapi.json

docs: ## Lint documentation locally
	npx --yes markdownlint-cli2 "**/*.md" "!**/node_modules/**" "!backend/.venv/**"

clean: ## Remove caches and build artifacts
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/htmlcov backend/coverage.xml
