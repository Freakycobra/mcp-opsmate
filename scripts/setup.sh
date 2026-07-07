#!/usr/bin/env bash
# =============================================================================
# mcp-opsmate — One-time Setup Script
# =============================================================================
# This script prepares your environment for running mcp-opsmate.
# It checks dependencies, creates the .env file, and pulls Docker images.
#
# Usage:
#   bash scripts/setup.sh
# =============================================================================

set -euo pipefail

# Colors
readonly BLUE='\033[0;34m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly RESET='\033[0m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║               mcp-opsmate — Setup                            ║"
echo "║         Infrastructure Automation MCP Terminal               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# =============================================================================
# Step 1: Check Docker
# =============================================================================
echo -e "${BLUE}[1/5]${RESET} Checking Docker installation..."
if ! command -v docker &>/dev/null; then
    echo -e "${RED}✗ Docker is not installed.${RESET}"
    echo "  Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

DOCKER_VERSION=$(docker --version | awk '{print $3}' | tr -d ',')
echo -e "${GREEN}✓${RESET} Docker version: ${DOCKER_VERSION}"

# =============================================================================
# Step 2: Check Docker Compose
# =============================================================================
echo -e "${BLUE}[2/5]${RESET} Checking Docker Compose..."
if docker compose version &>/dev/null; then
    COMPOSE_VERSION=$(docker compose version --short)
    echo -e "${GREEN}✓${RESET} Docker Compose v2: ${COMPOSE_VERSION}"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_VERSION=$(docker-compose --version | awk '{print $3}' | tr -d ',')
    echo -e "${GREEN}✓${RESET} Docker Compose v1: ${COMPOSE_VERSION}"
else
    echo -e "${RED}✗ Docker Compose is not installed.${RESET}"
    echo "  Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# =============================================================================
# Step 3: Create .env file
# =============================================================================
echo -e "${BLUE}[3/5]${RESET} Checking environment configuration..."
ENV_FILE="${PROJECT_ROOT}/.env"
ENV_TEMPLATE="${PROJECT_ROOT}/.env.template"

if [ -f "$ENV_FILE" ]; then
    echo -e "${GREEN}✓${RESET} .env file already exists."
    echo -e "  ${YELLOW}Tip:${RESET} Review your settings: cat .env"
else
    if [ -f "$ENV_TEMPLATE" ]; then
        cp "$ENV_TEMPLATE" "$ENV_FILE"
        echo -e "${GREEN}✓${RESET} Created .env from template."
        echo -e "  ${YELLOW}Tip:${RESET} Edit .env to configure LIVE mode integrations."
    else
        echo -e "${RED}✗ .env.template not found.${RESET}"
        echo "  Expected at: ${ENV_TEMPLATE}"
        exit 1
    fi
fi

# =============================================================================
# Step 4: Create required directories
# =============================================================================
echo -e "${BLUE}[4/5]${RESET} Creating required directories..."
mkdir -p "${PROJECT_ROOT}/opsmate"
mkdir -p "${PROJECT_ROOT}/opsmate-web"
mkdir -p "${PROJECT_ROOT}/scripts"
mkdir -p "${PROJECT_ROOT}/monitoring"
mkdir -p "${PROJECT_ROOT}/alembic/versions"
echo -e "${GREEN}✓${RESET} Directories created."

# =============================================================================
# Step 5: Pull Docker images
# =============================================================================
echo -e "${BLUE}[5/5]${RESET} Pulling Docker images..."
cd "$PROJECT_ROOT"
docker compose pull postgres redis 2>/dev/null || true
echo -e "${GREEN}✓${RESET} Base images pulled."

# =============================================================================
# Success
# =============================================================================
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${GREEN}║               Setup Complete!                                ║${RESET}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════════════╣${RESET}"
echo -e "${GREEN}║${RESET}  mcp-opsmate is ready to run.                               ${GREEN}║${RESET}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "${BLUE}Next Steps:${RESET}"
echo ""
echo "  1. Start in MOCK mode (default — no credentials needed):"
echo -e "     ${YELLOW}make up${RESET}"
echo ""
echo "  2. Start in development mode with hot-reload:"
echo -e "     ${YELLOW}make up-dev${RESET}"
echo ""
echo "  3. Run the interactive demo:"
echo -e "     ${YELLOW}make demo${RESET}"
echo ""
echo "  4. View all available commands:"
echo -e "     ${YELLOW}make help${RESET}"
echo ""
echo -e "${BLUE}Important URLs:${RESET}"
echo "  • Web UI:       http://localhost:8080"
echo "  • API Docs:     http://localhost:8080/docs"
echo "  • API Health:   http://localhost:8080/api/health"
echo ""
echo -e "${BLUE}Documentation:${RESET}"
echo "  • Edit .env to configure LIVE mode integrations"
echo "  • See README.md for full documentation"
echo ""
