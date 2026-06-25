# traj-lens — common dev & ops tasks. Run `make` (or `make help`) for the list.
.DEFAULT_GOAL := help
.PHONY: help install test typecheck build dev serve deploy smoke backup

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'

install: ## Install Python + web dependencies
	uv sync
	cd web && npm ci

test: ## Run the Python test suite
	uv run pytest tests/ -x -q

typecheck: ## TypeScript check (no emit)
	cd web && npx tsc --noEmit

build: ## Build the frontend bundle (web/dist)
	cd web && npm run build

dev: ## Run API with autoreload (development)
	uv run trajlens serve --reload

serve: ## Run API + web viewer (auto-builds stale web/dist)
	uv run trajlens serve

deploy: ## Pull, sync deps, rebuild web, restart service (server-side)
	./scripts/deploy.sh

smoke: ## Health-check a running server on :8000
	curl -fsS localhost:8000/api/health && echo " ok"

backup: ## Hot-backup the SQLite DB + blob dir
	sqlite3 $${TRAJLENS_DB:-trajlens.db} ".backup 'trajlens-$$(date +%F).db'"
	tar czf "blobs-$$(date +%F).tgz" $${TRAJLENS_BLOBS:-blobs}
