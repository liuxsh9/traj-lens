# traj-lens — common dev & ops tasks. Run `make` (or `make help`) for the list.
.DEFAULT_GOAL := help
.PHONY: help install test typecheck build dev serve deploy smoke backup worktree integrate

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

worktree: ## Spin up an isolated agent worktree+branch: make worktree NAME=fix-x
	@test -n "$(NAME)" || { echo "usage: make worktree NAME=<short-task-name>"; exit 1; }
	git worktree add "../tl-$(NAME)" -b "feat/$(NAME)"
	cd "../tl-$(NAME)" && uv sync >/dev/null
	@echo "✓ worktree ready: ../tl-$(NAME) (branch feat/$(NAME))"
	@echo "  edit + 'make test' there. Do NOT 'make serve' — only the main checkout serves :8000."

integrate: ## Merge an agent branch into main, test on the one shared stack: make integrate BR=feat/fix-x
	@test -n "$(BR)" || { echo "usage: make integrate BR=feat/<name>"; exit 1; }
	git rev-parse --abbrev-ref HEAD | grep -qx main || { echo "run from the main checkout"; exit 1; }
	git merge --no-ff "$(BR)"
	$(MAKE) test
	@echo "✓ $(BR) merged + tests pass. Restart serve / run 'make smoke' to QA, then push."

deploy: ## Pull, sync deps, rebuild web, restart service (server-side)
	./scripts/deploy.sh

smoke: ## Health-check a running server on :8000
	curl -fsS localhost:8000/api/health && echo " ok"

backup: ## Hot-backup the SQLite DB + blob dir
	sqlite3 $${TRAJLENS_DB:-trajlens.db} ".backup 'trajlens-$$(date +%F).db'"
	tar czf "blobs-$$(date +%F).tgz" $${TRAJLENS_BLOBS:-blobs}
