# =============================================================================
# mcp-opsmate — Makefile
# Infrastructure Automation MCP Terminal
# =============================================================================

.PHONY: help setup build up up-dev down logs test lint format db-migrate db-reset clean demo

# Default target
.DEFAULT_GOAL := help

# Colors
BLUE := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m

# =============================================================================
# Help
# =============================================================================
help: ## Show this help message
	@echo ""
	@echo "$(BLUE)╔══════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(BLUE)║              mcp-opsmate — Available Commands                ║$(RESET)"
	@echo "$(BLUE)╠══════════════════════════════════════════════════════════════╣$(RESET)"
	@echo "$(BLUE)║$(RESET)  make setup       — One-time project setup                   $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make build       — Build all Docker images                  $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make up          — Start full production stack              $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make up-dev      — Start development stack (hot-reload)     $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make down        — Stop all services                        $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make logs        — Tail logs from all services              $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make test        — Run pytest inside API container          $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make lint        — Run ruff + mypy linting                 $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make format      — Run ruff code formatter                  $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make db-migrate  — Run Alembic database migrations          $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make db-reset    — Reset database (drop + recreate)         $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make clean       — Remove containers, volumes, images       $(BLUE)║$(RESET)"
	@echo "$(BLUE)║$(RESET)  make demo        — Start in MOCK mode with demo data        $(BLUE)║$(RESET)"
	@echo "$(BLUE)╚══════════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""

# =============================================================================
# Setup
# =============================================================================
setup: ## One-time setup: create .env, pull images, create directories
	@echo "$(BLUE)[setup]$(RESET) Setting up mcp-opsmate..."
	@bash scripts/setup.sh

# =============================================================================
# Build
# =============================================================================
build: ## Build all Docker images
	@echo "$(BLUE)[build]$(RESET) Building Docker images..."
	docker compose build --parallel
	@echo "$(GREEN)[build]$(RESET) All images built successfully."

# =============================================================================
# Start / Stop
# =============================================================================
up: ## Start full production stack (api + web + postgres + redis + nginx)
	@echo "$(BLUE)[up]$(RESET) Starting production stack..."
	@test -f .env || (echo "$(YELLOW)[up]$(RESET) .env not found, creating from template..." && cp .env.template .env)
	docker compose up -d postgres redis api web nginx
	@echo "$(GREEN)[up]$(RESET) Production stack is running!"
	@echo "$(GREEN)[up]$(RESET)   → Web UI:     http://localhost:8080"
	@echo "$(GREEN)[up]$(RESET)   → API docs:   http://localhost:8080/docs"
	@echo "$(GREEN)[up]$(RESET)   → API health: http://localhost:8080/api/health"

up-dev: ## Start development stack (api-dev + web-dev + postgres + redis)
	@echo "$(BLUE)[up-dev]$(RESET) Starting development stack with hot-reload..."
	@test -f .env || (echo "$(YELLOW)[up-dev]$(RESET) .env not found, creating from template..." && cp .env.template .env)
	docker compose --profile dev up -d postgres redis api-dev web-dev
	@echo "$(GREEN)[up-dev]$(RESET) Dev stack is running!"
	@echo "$(GREEN)[up-dev]$(RESET)   → Web Dev:    http://localhost:5173"
	@echo "$(GREEN)[up-dev]$(RESET)   → API Dev:    http://localhost:8000"
	@echo "$(GREEN)[up-dev]$(RESET)   → API docs:   http://localhost:8000/docs"
	@echo "$(YELLOW)[up-dev]$(RESET) Hot-reload enabled for both frontend and backend."

up-monitoring: ## Start with Prometheus monitoring (--profile monitoring)
	@echo "$(BLUE)[up-monitoring]$(RESET) Starting with Prometheus monitoring..."
	@test -f .env || cp .env.template .env
	docker compose --profile monitoring up -d
	@echo "$(GREEN)[up-monitoring]$(RESET) Stack with monitoring is running!"
	@echo "$(GREEN)[up-monitoring]$(RESET)   → Prometheus: http://localhost:9090"

up-aws: ## Start with LocalStack AWS emulator (--profile aws)
	@echo "$(BLUE)[up-aws]$(RESET) Starting with LocalStack..."
	@test -f .env || cp .env.template .env
	docker compose --profile aws up -d
	@echo "$(GREEN)[up-aws]$(RESET) Stack with LocalStack is running!"
	@echo "$(GREEN)[up-aws]$(RESET)   → LocalStack: http://localhost:4566"

down: ## Stop all services
	@echo "$(BLUE)[down]$(RESET) Stopping all services..."
	docker compose --profile dev --profile monitoring --profile aws down
	@echo "$(GREEN)[down]$(RESET) All services stopped."

# =============================================================================
# Logs
# =============================================================================
logs: ## Tail logs from all services
	@echo "$(BLUE)[logs]$(RESET) Tailing logs (Ctrl+C to exit)..."
	docker compose logs -f --tail=50

logs-api: ## Tail logs from API service only
	@echo "$(BLUE)[logs-api]$(RESET) Tailing API logs..."
	docker compose logs -f --tail=50 api

logs-db: ## Tail logs from PostgreSQL only
	@echo "$(BLUE)[logs-db]$(RESET) Tailing PostgreSQL logs..."
	docker compose logs -f --tail=50 postgres

# =============================================================================
# Testing
# =============================================================================
test: ## Run pytest inside API container
	@echo "$(BLUE)[test]$(RESET) Running tests..."
	docker compose exec api pytest -xvs --tb=short
	@echo "$(GREEN)[test]$(RESET) Tests complete."

test-cov: ## Run tests with coverage report
	@echo "$(BLUE)[test-cov]$(RESET) Running tests with coverage..."
	docker compose exec api pytest --cov=opsmate --cov-report=term-missing --cov-report=html

# =============================================================================
# Linting & Formatting
# =============================================================================
lint: ## Run ruff + mypy linting
	@echo "$(BLUE)[lint]$(RESET) Running ruff check..."
	docker compose exec api ruff check .
	@echo "$(BLUE)[lint]$(RESET) Running mypy..."
	docker compose exec api mypy opsmate/
	@echo "$(GREEN)[lint]$(RESET) Linting complete."

format: ## Run ruff code formatter
	@echo "$(BLUE)[format]$(RESET) Running ruff format..."
	docker compose exec api ruff format .
	@echo "$(GREEN)[format]$(RESET) Formatting complete."

lint-fix: ## Run ruff check with auto-fix
	@echo "$(BLUE)[lint-fix]$(RESET) Running ruff check --fix..."
	docker compose exec api ruff check --fix .
	@echo "$(GREEN)[lint-fix]$(RESET) Auto-fix complete."

# =============================================================================
# Database
# =============================================================================
db-migrate: ## Run Alembic database migrations
	@echo "$(BLUE)[db-migrate]$(RESET) Running database migrations..."
	docker compose exec api alembic upgrade head
	@echo "$(GREEN)[db-migrate]$(RESET) Migrations applied."

db-reset: ## Reset database (drop + recreate + migrate)
	@echo "$(RED)[db-reset]$(RESET) This will DESTROY all data in the database."
	@read -p "Are you sure? [y/N]: " confirm && [ "$$confirm" = "y" ] || (echo "Aborted." && exit 1)
	@echo "$(BLUE)[db-reset]$(RESET) Stopping API..."
	docker compose stop api api-dev 2>/dev/null || true
	@echo "$(BLUE)[db-reset]$(RESET) Dropping and recreating database..."
	docker compose exec postgres psql -U $(POSTGRES_USER:-opsmate) -d postgres -c "DROP DATABASE IF EXISTS $(POSTGRES_DB:-opsmate);" || true
	docker compose exec postgres psql -U $(POSTGRES_USER:-opsmate) -d postgres -c "CREATE DATABASE $(POSTGRES_DB:-opsmate);" || true
	@echo "$(BLUE)[db-reset]$(RESET) Running migrations..."
	docker compose start api 2>/dev/null || true
	docker compose exec api alembic upgrade head
	@echo "$(GREEN)[db-reset]$(RESET) Database reset complete."

db-shell: ## Open PostgreSQL interactive shell
	@echo "$(BLUE)[db-shell]$(RESET) Opening PostgreSQL shell..."
	docker compose exec postgres psql -U $(POSTGRES_USER:-opsmate) -d $(POSTGRES_DB:-opsmate)

db-seed: ## Seed database with demo data
	@echo "$(BLUE)[db-seed]$(RESET) Seeding demo data..."
	docker compose exec api python scripts/seed_demo_data.py
	@echo "$(GREEN)[db-seed]$(RESET) Demo data seeded."

# =============================================================================
# Cleanup
# =============================================================================
clean: ## Remove all containers, volumes, images, and build cache
	@echo "$(RED)[clean]$(RESET) This will remove ALL containers, volumes, and images."
	@read -p "Are you sure? [y/N]: " confirm && [ "$$confirm" = "y" ] || (echo "Aborted." && exit 1)
	@echo "$(BLUE)[clean]$(RESET) Stopping and removing containers..."
	docker compose --profile dev --profile monitoring --profile aws down -v --remove-orphans
	@echo "$(BLUE)[clean]$(RESET) Removing build cache..."
	docker system prune -f
	@echo "$(GREEN)[clean]$(RESET) Cleanup complete."

# =============================================================================
# Demo
# =============================================================================
demo: ## Start in MOCK mode and show demo commands
	@echo "$(GREEN)╔══════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(GREEN)║               mcp-opsmate — Demo Mode                        ║$(RESET)"
	@echo "$(GREEN)╠══════════════════════════════════════════════════════════════╣$(RESET)"
	@echo "$(GREEN)║$(RESET)  Starting in MOCK mode — no credentials needed.              $(GREEN)║$(RESET)"
	@echo "$(GREEN)╚══════════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""
	@cp .env.template .env 2>/dev/null || true
	@sed -i 's/OPSMATE_MODE=.*/OPSMATE_MODE=mock/' .env
	@echo "$(BLUE)[demo]$(RESET) Starting services..."
	@docker compose up -d postgres redis api web nginx
	@echo ""
	@echo "$(GREEN)[demo]$(RESET) Services are starting up..."
	@sleep 5
	@echo ""
	@echo "$(GREEN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "$(GREEN)  Quick Demo Commands:                                        $(RESET)"
	@echo "$(GREEN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo ""
	@echo "  $(YELLOW)1. Check API health:$(RESET)"
	@echo "     curl http://localhost:8080/api/health"
	@echo ""
	@echo "  $(YELLOW)2. List executions:$(RESET)"
	@echo "     curl http://localhost:8080/api/executions"
	@echo ""
	@echo "  $(YELLOW)3. Create an execution (MOCK):$(RESET)"
	@echo '     curl -X POST http://localhost:8080/api/execute \\"
	@echo "       -H 'Content-Type: application/json' \\"
	@echo '       -d '{"command": "deploy nginx to production"}
	@echo ""
	@echo "  $(YELLOW)4. View API docs (interactive):$(RESET)"
	@echo "     http://localhost:8080/docs"
	@echo ""
	@echo "  $(YELLOW)5. Open web UI:$(RESET)"
	@echo "     http://localhost:8080"
	@echo ""
	@echo "  $(YELLOW)6. Seed demo data:$(RESET)"
	@echo "     make db-seed"
	@echo ""
	@echo "  $(YELLOW)7. View logs:$(RESET)"
	@echo "     make logs"
	@echo ""
	@echo "  $(YELLOW)8. Stop all services:$(RESET)"
	@echo "     make down"
	@echo ""
	@echo "$(GREEN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
