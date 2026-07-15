#!/usr/bin/env bash
# =============================================================================
# mcp-opsmate — One-Command Setup Script
# =============================================================================
# Usage: ./setup.sh
#   - Checks prerequisites (Docker, Docker Compose, git)
#   - Creates .env file from template
#   - Prompts for API credentials (optional — MOCK mode works without them)
#   - Builds and starts the full stack
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

print_banner() {
    echo ""
    echo "============================================================"
    echo "  mcp-opsmate — Infrastructure Automation MCP Terminal"
    echo "============================================================"
    echo ""
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed."
        echo "  Install: https://docs.docker.com/get-docker/"
        exit 1
    fi
    log_ok "Docker installed: $(docker --version | cut -d' ' -f3 | tr -d ',')"

    if ! docker compose version &> /dev/null 2>&1; then
        if ! docker-compose --version &> /dev/null 2>&1; then
            log_error "Docker Compose is not installed."
            echo "  Install: https://docs.docker.com/compose/install/"
            exit 1
        fi
    fi
    log_ok "Docker Compose installed"

    if ! command -v git &> /dev/null; then
        log_warn "Git not found (optional — only needed for updates)"
    else
        log_ok "Git installed"
    fi

    echo ""
}

create_env_file() {
    if [ -f ".env" ]; then
        log_warn ".env file already exists. Skipping creation."
        echo "  Delete it first if you want to recreate: rm .env"
        echo ""
        return
    fi

    log_info "Creating .env file from template..."
    cp .env.template .env
    log_ok ".env created"

    echo ""
    echo "------------------------------------------------------------"
    echo "  API Credentials (Optional — MOCK mode works without them)"
    echo "------------------------------------------------------------"
    echo ""
    echo "Press ENTER to skip any prompt and use MOCK mode."
    echo "You can always edit .env later to add credentials."
    echo ""

    # OpenAI API Key (required even for mock, for intent classification)
    read -rp "OpenAI API Key (required): " openai_key
    if [ -n "$openai_key" ]; then
        sed -i.bak "s|OPENAI_API_KEY=.*|OPENAI_API_KEY=$openai_key|" .env && rm -f .env.bak
        log_ok "OpenAI API Key configured"
    else
        log_warn "No OpenAI key provided — intent classification will use basic regex only"
    fi

    # Tavily
    read -rp "Tavily API Key (optional, for web search): " tavily_key
    if [ -n "$tavily_key" ]; then
        sed -i.bak "s|TAVILY_API_KEY=.*|TAVILY_API_KEY=$tavily_key|" .env && rm -f .env.bak
        log_ok "Tavily configured"
    fi

    # GitHub
    read -rp "GitHub PAT (optional, for repo/CI info): " github_pat
    if [ -n "$github_pat" ]; then
        sed -i.bak "s|GITHUB_PAT=.*|GITHUB_PAT=$github_pat|" .env && rm -f .env.bak
        log_ok "GitHub configured"
    fi

    # Slack
    read -rp "Slack Webhook URL (optional, for alerts): " slack_url
    if [ -n "$slack_url" ]; then
        sed -i.bak "s|SLACK_WEBHOOK_URL=.*|SLACK_WEBHOOK_URL=$slack_url|" .env && rm -f .env.bak
        log_ok "Slack configured"
    fi

    # Jira
    read -rp "Jira Base URL (optional, e.g., https://yourdomain.atlassian.net): " jira_url
    if [ -n "$jira_url" ]; then
        sed -i.bak "s|JIRA_BASE_URL=.*|JIRA_BASE_URL=$jira_url|" .env && rm -f .env.bak
        read -rp "Jira Email: " jira_email
        sed -i.bak "s|JIRA_EMAIL=.*|JIRA_EMAIL=$jira_email|" .env && rm -f .env.bak
        read -rp "Jira API Token: " jira_token
        sed -i.bak "s|JIRA_API_TOKEN=.*|JIRA_API_TOKEN=$jira_token|" .env && rm -f .env.bak
        log_ok "Jira configured"
    fi

    echo ""
    log_ok ".env configuration complete"
    echo ""
}

build_and_start() {
    log_info "Building Docker images (this may take a few minutes)..."
    docker compose build --no-cache
    log_ok "Build complete"

    echo ""
    log_info "Starting services..."
    docker compose up -d
    log_ok "Services started"

    echo ""
    echo "============================================================"
    echo "  mcp-opsmate is running!"
    echo "============================================================"
    echo ""
    echo "  Web UI:     http://localhost:8080"
    echo "  API Docs:   http://localhost:8080/docs"
    echo "  API:        http://localhost:8080/api"
    echo "  Health:     http://localhost:8080/health"
    echo "  Prometheus: http://localhost:9090 (if --profile monitoring)"
    echo ""
    echo "  CLI Usage:"
    echo "    cd opsmate-cli && pip install -e ."
    echo "    opsmate run \"Check payment-service pods, restart if CPU > 80%\""
    echo ""
    echo "  Useful commands:"
    echo "    docker compose logs -f api     # Watch API logs"
    echo "    docker compose ps              # Check service status"
    echo "    docker compose down            # Stop all services"
    echo "    make help                      # Show all available commands"
    echo ""
    echo "  Mode: MOCK (all integrations use synthetic data)"
    echo "  To switch to LIVE mode: edit .env → OPSMATE_MODE=live → docker compose restart"
    echo ""
}

main() {
    print_banner
    check_prerequisites
    create_env_file
    build_and_start
}

main "$@"
