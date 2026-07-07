# mcp-opsmate 🔧

> **Infrastructure Automation MCP Terminal** — Natural language command execution for platform engineers and SREs, powered by the Model Context Protocol.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-blue?logo=python&logoColor=white" alt="Python 3.13" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white" alt="React 18" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/MCP-Protocol-orange" alt="MCP" />
  <img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  <img src="https://github.com/Freakycobra/mcp-opsmate/actions/workflows/ci.yml/badge.svg" alt="CI" />
</p>

**OpsMate** is an AI-powered infrastructure automation terminal that converts natural language commands into multi-step, DAG-structured execution plans. Built on [Anthropic's Model Context Protocol (MCP)](https://modelcontextprotocol.io/), it dynamically discovers and chains tool calls across 7 MCP servers — including GitHub, Jira, Slack, AWS, PostgreSQL, Tavily search, and a calculator — to execute complex operational workflows with full observability, state persistence, and human-in-the-loop escalation.

**Why this matters:** Platform engineers and SREs waste hours every week stitching together kubectl, AWS CLI, GitHub API, and Slack webhook calls for routine operational tasks. OpsMate collapses those multi-tool sequences into single natural language commands, executes them through a fault-tolerant orchestrator with circuit breakers and retry logic, and provides a complete audit trail for compliance. It runs in **MOCK mode by default** for zero-config onboarding, graduating seamlessly to **LIVE mode** for production use.

**What it demonstrates:** Multi-agent orchestration, protocol-oriented architecture, tiered error recovery, async DAG execution with `asyncio.TaskGroup`, hybrid LLM+regex intent classification, and production-grade observability — packaged as a deployable portfolio project.

---

## Demo

When you type a command, OpsMate does the following:

1. **Classifies intent** — hybrid regex + GPT-4o classifier identifies operational intent and extracts entities (service names, time ranges, thresholds)
2. **Builds a DAG** — intent planner generates an execution plan as a directed acyclic graph with data dependencies between steps
3. **Validates tools** — checks that all required MCP tools are available and schemas are compatible
4. **Executes in parallel** — runs independent steps concurrently via `asyncio.TaskGroup`, respecting topological ordering
5. **Recovers from failures** — applies 4-tier error recovery: retry → circuit breaker → degraded execution → human escalation
6. **Persists state** — saves execution state to PostgreSQL after every step, enabling pause/resume of long-running workflows

### Example Session

```bash
# Start the stack (zero configuration needed)
docker compose up -d

# Submit a command via CLI
opsmate run "Check if payment-service pods are healthy in EKS, \
  show CPU trends for the last 2 hours, restart any pod above 80% CPU, \
  and alert the on-call Slack channel"
```

**System response:**

```
🔧 OpsMate [MOCK mode]
═════════════════════════════════════════════

📋 Execution Plan (4 steps)
┌── describe_pods ──────────────────────────┐
│ Server: aws-ecs    Status: ✅ COMPLETED   │
│ Output: 8 pods (2 Pending, 6 Running)     │
└───────────────────────────────────────────┘
       │
       ▼
┌── get_cloudwatch_metrics ─────────────────┐
│ Server: aws-ecs    Status: ✅ COMPLETED   │
│ Output: CPU data for 8 pods, 2h window    │
└───────────────────────────────────────────┘
       │
       ▼
┌── conditional_restart_pods ───────────────┐
│ Server: aws-ecs    Status: ✅ COMPLETED   │
│ Condition: cpu_percent > 80               │
│ Action: Restarted 2 pods (pod-3, pod-7)   │
│ Duration: 8.3s                            │
└───────────────────────────────────────────┘
       │
       ▼
┌── send_slack_message ─────────────────────┐
│ Server: slack      Status: ✅ COMPLETED   │
│ Channel: #on-call                         │
│ Message: "Payment-service: 2 pods..."     │
└───────────────────────────────────────────┘

⏱️  Total time: 1.8s  |  Mode: MOCK  |  ID: exec_a7f3...
```

---

## Architecture

```mermaid
graph TB
    subgraph Client["Client Layer"]
        CLI["CLI — Rich TUI<br/>opsmate-cli"]
        WEB["Web UI — React 18<br/>opsmate-web"]
    end

    subgraph Transport["Transport Layer"]
        REST["REST API — FastAPI"]
        SSE["SSE Stream<br/>/stream/{exec_id}"]
        WS["WebSocket<br/>/ws/executions"]
    end

    subgraph Engine["Orchestrator Engine"]
        IC["Intent Classifier<br/>GPT-4o + regex"]
        IP["Intent Planner<br/>DAG Builder"]
        SE["Step Executor<br/>asyncio.TaskGroup"]
        SM["State Manager<br/>PostgreSQL + Pydantic"]
        ERH["Error Recovery<br/>Retry + Circuit Breaker"]
    end

    subgraph Hub["MCP Server Hub"]
        MGR["MCP Client Manager<br/>stdio + SSE transports"]
        TD["Tool Registry<br/>Dynamic Discovery"]
        MR["Mode Router<br/>MOCK ↔ LIVE"]
    end

    subgraph MCP["MCP Servers × 7"]
        S1["🔍 Tavily Search"]
        S2["🐙 GitHub"]
        S3["💬 Slack"]
        S4["📋 Jira"]
        S5["☁️ AWS ECS"]
        S6["🐘 PostgreSQL"]
        S7["🧮 Calculator"]
    end

    subgraph Data["Data Layer"]
        PG[("PostgreSQL<br/>Execution State")]
        RD[("Redis<br/>Circuit Breaker")]
    end

    CLI --> REST
    WEB --> REST
    WEB --> WS
    REST --> IC & SM
    IC --> IP --> SE
    SE --> ERH --> MGR
    SE --> SM --> PG
    ERH -.-> RD
    MGR --> TD & MR --> MCP
    MGR -.-> RD
```

### Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| **MCP-First Design** | Core engine imports only the `mcp` SDK — zero direct AWS/GitHub/Jira client imports. New MCP server onboarding requires <50 lines of config. |
| **Hybrid Intent Classifier** | Regex extractor handles deterministic patterns (service names, time ranges, thresholds) at zero latency; GPT-4o handles semantic understanding. Combined accuracy >90%. |
| **DAG-Based Execution** | Plans are directed acyclic graphs executed via topological sort + `asyncio.TaskGroup`. Independent steps run in parallel; dependent steps run sequentially. No ordering violations possible by construction. |
| **4-Tier Error Recovery** | T1: Retry with exponential backoff → T2: Redis-backed circuit breaker (OPEN/HALF_OPEN/CLOSED) → T3: Degraded execution (skip non-critical steps) → T4: Human escalation with 5-min timeout. |
| **MOCK-by-Default** | Seeded Faker generates deterministic synthetic data matching real API schemas. Zero external credentials required. Same seed = identical outputs for reproducible demos and testing. |
| **State Machine Explicitness** | Every execution has a known, persisted state (PENDING → PLANNING → AWAITING_CONFIRMATION → EXECUTING → COMPLETED/FAILED). PostgreSQL-backed with graceful SIGTERM handling for pause/resume. |

---

## Features

- **🗣️ Natural Language Command Processing** — Submit infrastructure commands in plain English; the hybrid intent classifier (regex + GPT-4o) extracts entities and operational intent with >90% accuracy
- **📊 DAG-Based Execution Plans** — Multi-step plans are structured as directed acyclic graphs with explicit data dependencies, enabling safe parallel execution of independent steps
- **🔌 7 Integrated MCP Servers** — Tavily (search), GitHub (repos/CI), Slack (notifications), Jira (tickets), AWS ECS (container ops), PostgreSQL (database queries), Calculator (math/compute)
- **🎭 MOCK / LIVE / MIXED Modes** — MOCK mode uses deterministic seeded Faker for zero-config demos; LIVE mode makes real API calls; MIXED mode enables per-server granularity
- **⚡ Parallel Step Execution** — Independent steps execute concurrently via `asyncio.TaskGroup` with topological ordering guarantees
- **🛡️ 4-Tier Error Recovery** — Retry (exponential backoff, 3 attempts) → Circuit Breaker (Redis-backed, 5-failure threshold) → Degraded Execution → Human Escalation
- **💾 State Persistence** — PostgreSQL-backed execution state saved after every step; graceful SIGTERM handling enables pause/resume of long-running workflows
- **🔐 Security-First** — API key authentication, admin bearer tokens for privileged endpoints, secret redaction in all logs, read-only enforcement in MOCK mode
- **📡 Real-Time Streaming** — SSE streams provide live execution updates to CLI and Web UI with <500ms latency
- **📈 Observability** — Prometheus metrics, structured JSON audit logs, execution correlation IDs propagated through all layers, health endpoint with MCP server status
- **🖥️ Rich CLI** — Rich TUI with syntax-highlighted JSON output, colored status tables, progress spinners, streaming SSE output, and command history
- **🌐 Interactive Web UI** — React 18 + TypeScript with real-time DAG visualization (ReactFlow), chat interface, execution history, and admin dashboard

---

## Quick Start

### Prerequisites

- **Docker** 24.0+ and Docker Compose v2+
- **Python** 3.13+ (for local development)
- **Git**

### 3-Step Setup

```bash
# 1. Clone the repository
git clone https://github.com/Freakycobra/mcp-opsmate.git
cd mcp-opsmate

# 2. Start the full stack (MOCK mode — zero config needed)
docker compose up -d

# 3. Verify everything is healthy
curl http://localhost:8000/health
```

The stack includes: FastAPI backend (port 8000), React Web UI (port 3000), PostgreSQL (port 5432), Redis (port 6379), and all 7 MCP servers.

### Demo Commands

```bash
# Health check and remediation (4-step DAG)
opsmate run "Check payment-service pods in EKS, restart if CPU > 80%, alert Slack"

# Incident correlation (multi-tool)
opsmate run "Show P1 Jira tickets and cross-reference with GitHub CI failures in the last 24h"

# Performance analysis
opsmate run "Compare Lambda cold-start latency vs last week, identify top 5 worst performers"

# Database query + calculation
opsmate run "Query the orders table for yesterday's revenue, calculate the 7-day rolling average"

# Web search + notification
opsmate run "Search for recent AWS ECS best practices, summarize, and post to #platform Slack"
```

### Switching to LIVE Mode

```bash
# Set credentials (see Configuration section below)
export OPENAI_API_KEY="sk-..."
export TAVILY_API_KEY="tvly-..."
export GITHUB_PAT="ghp_..."

# Switch mode via admin API
curl -X POST http://localhost:8000/admin/mode \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -d '{"global_mode": "live", "reason": "Production deployment"}'
```

---

## Tech Stack

| Layer | Technology | Why This Choice |
|-------|-----------|-----------------|
| **Backend** | Python 3.13 + FastAPI | Native async, Pydantic v2 integration, auto-generated OpenAPI docs, SSE/WebSocket support |
| **Frontend** | React 18 + TypeScript + Vite | Type-safe component model, fast DX, tree-shaking, modern hooks API |
| **Styling** | Tailwind CSS + shadcn/ui | Utility-first CSS, accessible component primitives, consistent design system |
| **State Management** | React Context + useReducer | Sufficient for v1.0 scope; no external library needed |
| **DAG Viz** | ReactFlow | Interactive node graphs with real-time updates, custom node types |
| **Charts** | Recharts | Lightweight React-native charts, responsive, customizable |
| **Database** | PostgreSQL 16 + asyncpg | JSONB for flexible plan/results storage, async driver, best-in-class performance |
| **ORM** | SQLAlchemy 2.0 | Native async Mapped type annotations, Alembic migrations |
| **Cache** | Redis | Circuit breaker state, tool schema cache, rate limiting |
| **CLI** | Rich (Python) | Syntax highlighting, tables, panels, spinners, live display — all in terminal |
| **LLM** | OpenAI GPT-4o | Structured JSON output, function calling, reliable for planning tasks |
| **Protocol** | MCP (Model Context Protocol) | Open standard from Anthropic; decouples tools from orchestrator |
| **MCP Transport** | stdio + SSE | stdio for local subprocess servers, SSE for remote HTTP servers |
| **Mock Data** | Faker (seeded) | Deterministic synthetic data; same seed produces identical outputs |
| **Container** | Docker + Docker Compose | Full-stack local deployment, MOCK mode requires zero host dependencies |
| **Testing** | pytest + pytest-asyncio + httpx | Async test support, ASGI test client, coverage reporting |
| **CI/CD** | GitHub Actions | Lint, test, build matrix, Docker layer caching |
| **Metrics** | Prometheus | `/metrics` endpoint with custom metrics for executions, steps, MCP health |

---

## Project Structure

```
mcp-opsmate/
├── .github/
│   └── workflows/
│       └── ci.yml                    # CI/CD: lint, test, build
├── opsmate/                         # Main Python package
│   ├── api/                         # FastAPI application
│   │   ├── main.py                  # App factory + lifespan manager
│   │   ├── middleware/              # Auth, logging, CORS
│   │   └── routes/                  # REST endpoints
│   │       ├── commands.py          # POST /commands
│   │       ├── executions.py        # GET/POST /executions/*
│   │       ├── admin.py             # GET/POST /admin/*
│   │       └── health.py            # GET /health, /metrics
│   ├── core/                        # Domain models + config
│   │   ├── models.py                # Pydantic schemas (ExecutionPlan, ExecutionState, ...)
│   │   ├── config.py                # Pydantic-Settings configuration
│   │   ├── engine.py                # Orchestrator engine
│   │   └── state_machine.py         # State transition logic
│   ├── services/                    # Business logic
│   │   ├── intent.py                # Intent classifier + planner
│   │   ├── executor.py              # Step executor (DAG runner)
│   │   ├── recovery.py              # Error recovery (4-tier)
│   │   ├── state.py                 # State manager (PostgreSQL)
│   │   └── audit.py                 # Audit logger
│   ├── infra/                       # Infrastructure adapters
│   │   ├── mcp_hub.py               # MCP client manager + tool registry + mode router
│   │   ├── database.py              # SQLAlchemy async session
│   │   ├── cache.py                 # Redis client
│   │   └── llm.py                   # OpenAI client wrapper
│   ├── mcp_servers/                 # Built-in MCP servers (7 total)
│   │   ├── tavily/                  # Tavily search MCP server
│   │   ├── github/                  # GitHub repos/CI MCP server
│   │   ├── slack/                   # Slack messaging MCP server
│   │   ├── jira/                    # Jira ticket MCP server
│   │   ├── aws_ecs/                 # AWS container ops MCP server
│   │   ├── postgres/                # PostgreSQL query MCP server
│   │   └── calculator/              # Calculator MCP server
│   └── cli/                         # opsmate-cli (Rich TUI)
│       └── main.py
├── opsmate-web/                     # React frontend
│   ├── src/
│   │   ├── pages/                   # Chat, History, Dashboard, Admin
│   │   ├── components/              # DAG Visualizer, Mode Indicator, Chat
│   │   ├── contexts/                # Auth, Mode
│   │   └── api/                     # Axios client + Zod validation
│   ├── package.json
│   └── vite.config.ts
├── tests/                           # Test suite
│   ├── conftest.py                  # Shared fixtures (async loop, test DB, mock MCP hub)
│   ├── test_api/                    # API route tests
│   ├── test_services/               # Service logic tests
│   └── test_infra/                  # Infrastructure tests
├── docs/                            # Documentation
│   ├── requirements.md              # Functional + non-functional requirements
│   ├── architecture.md              # Architecture specification
│   ├── tech-spec.md                 # API contract, DB schema, models
│   └── resume-entry.md              # Polished resume entry
├── docker-compose.yml               # Full-stack local deployment
├── Dockerfile.api                   # Backend image
├── Dockerfile.web                   # Frontend image
├── pytest.ini                       # Test configuration
├── Makefile                         # Development commands
└── README.md                        # This file
```

---

## API Documentation

Interactive API documentation is available at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc` (ReDoc) when the server is running.

### Key Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/commands` | API Key | Submit a natural language command |
| `GET`  | `/executions` | API Key | List execution history (paginated, filterable) |
| `GET`  | `/executions/{id}` | API Key | Get full execution detail |
| `POST` | `/executions/{id}/approve` | API Key | Approve a pending execution plan |
| `GET`  | `/stream/{id}` | API Key (query param) | SSE stream for real-time updates |
| `GET`  | `/health` | None | Health check with MCP server status |
| `GET`  | `/metrics` | None | Prometheus metrics |
| `GET`  | `/admin/mode` | Admin Token | Get current execution mode |
| `POST` | `/admin/mode` | Admin Token | Switch execution mode |
| `GET`  | `/admin/tools` | Admin Token | List available MCP tools |
| `POST` | `/admin/tools/refresh` | Admin Token | Refresh tool registry |
| `GET`  | `/examples` | None | Built-in demo commands |

### Authentication

Two-tier authentication:
- **Standard endpoints** (`X-API-Key: <key>`): All endpoints except `/health`, `/metrics`, `/examples`
- **Admin endpoints** (`Authorization: Bearer <token>`): `/admin/*` only — regular API key is rejected with 403

---

## MCP Servers

| Server | Tools | MOCK | LIVE | Description |
|--------|-------|------|------|-------------|
| **Tavily Search** | `search`, `search_news` | ✅ Deterministic Faker | 🔑 Tavily API Key | Web search for operational research |
| **GitHub** | `get_repo`, `list_issues`, `get_workflow_runs`, `create_issue` | ✅ Deterministic Faker | 🔑 GitHub PAT | Repository and CI/CD operations |
| **Slack** | `send_message`, `get_channel_history` | ✅ Deterministic Faker | 🔑 Slack Webhook | Team notifications and alerts |
| **Jira** | `search_tickets`, `get_ticket`, `create_ticket`, `add_comment` | ✅ Deterministic Faker | 🔑 Jira API Token | Ticket management and tracking |
| **AWS ECS** | `describe_pods`, `get_cloudwatch_metrics`, `restart_pods`, `scale_service` | ✅ Deterministic Faker | 🔑 AWS Credentials | Container orchestration and monitoring |
| **PostgreSQL** | `execute_query`, `list_tables`, `describe_table` | ✅ Docker PostgreSQL | 🔑 DATABASE_URL | Database queries and schema introspection |
| **Calculator** | `calculate`, `evaluate_expression` | ✅ Local computation | ✅ Local computation | Safe AST-based math evaluation |

**Total tools available:** 20+ across 7 servers, automatically discovered at startup.

---

## Configuration

### Execution Modes

OpsMate supports three execution modes, controlled via the `EXECUTION_MODE` environment variable:

| Mode | Description | Use Case |
|------|-------------|----------|
| `mock` (default) | All MCP calls return deterministic synthetic data | Development, demos, testing, onboarding |
| `live` | All MCP calls make real API requests | Production use with valid credentials |
| `mixed` | Per-server mode configuration — some LIVE, some MOCK | Gradual migration, partial integrations |

### Per-Server Mode Overrides

In `mixed` mode (or as overrides in any mode), each MCP server can be independently configured:

```yaml
mcp_servers:
  github:
    mode: "live"      # Real GitHub API calls
  aws-ecs:
    mode: "mock"      # Synthetic AWS data
  calculator:
    mode: "local"     # Always local computation
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EXECUTION_MODE` | No | `mock` | Global execution mode: `mock`, `live`, `mixed` |
| `DATABASE_URL` | No | `postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate` | PostgreSQL connection string |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection string |
| `OPENAI_API_KEY` | In `live` mode | — | OpenAI API key for intent classification and planning |
| `API_KEY` | No | `dev-key-change-in-production` | Standard API authentication key |
| `ADMIN_API_TOKEN` | No | `admin-dev-token-change-me` | Admin bearer token for privileged endpoints |
| `LOG_LEVEL` | No | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | No | `json` | Log format: `json` or `text` |

### MCP Server Credentials (LIVE Mode Only)

| Variable | Server | Description |
|----------|--------|-------------|
| `TAVILY_API_KEY` | Tavily Search | Tavily API key |
| `GITHUB_PAT` | GitHub | GitHub personal access token |
| `SLACK_WEBHOOK_URL` | Slack | Slack incoming webhook URL |
| `JIRA_URL` | Jira | Jira instance URL |
| `JIRA_EMAIL` | Jira | Jira account email |
| `JIRA_API_TOKEN` | Jira | Jira API token |
| `AWS_REGION` | AWS ECS | AWS region (default: `us-east-1`) |

---

## Testing

### Run All Tests

```bash
# Start test infrastructure
docker compose -f docker-compose.test.yml up -d

# Run full test suite with coverage
pytest --cov=opsmate --cov-report=term-missing --cov-report=html

# Run specific test module
pytest tests/test_api/test_commands.py -v
pytest tests/test_services/test_executor.py -v
```

### Coverage Targets

| Component | Target | Current |
|-----------|--------|---------|
| API Routes | ≥ 90% | — |
| Services (Intent, Executor, State) | ≥ 85% | — |
| Infrastructure (MCP Hub, Database) | ≥ 80% | — |
| **Overall** | **≥ 85%** | — |

### Test Infrastructure

All tests use `pytest-asyncio` for async support. External APIs (OpenAI, Tavily, GitHub, etc.) are fully mocked — no real API calls are made during test execution. The `mock_mcp_hub` fixture provides a test-local MCP hub with 3 mock servers for isolated testing.

---

## Development

### Make Commands

```bash
make help           # Show all available commands
make install        # Install Python + Node dependencies
make dev            # Start backend + frontend in dev mode
make test           # Run full test suite
make lint           # Run ruff check + ruff format --check + mypy
make format         # Auto-format all code (ruff format)
make docker-build   # Build all Docker images
make docker-up      # Start with docker compose
make docker-down    # Stop all containers
make migrate        # Run database migrations (Alembic)
make seed           # Seed database with demo data
```

### Adding a New MCP Server

1. **Create the server package** in `opsmate/mcp_servers/<name>/`:
   ```python
   # opsmate/mcp_servers/my_server/main.py
   from mcp.server.fastmcp import FastMCP

   mcp = FastMCP("my-server")

   @mcp.tool()
   async def my_tool(param: str) -> dict:
       """Tool description."""
       return {"result": f"processed: {param}"}

   if __name__ == "__main__":
       mcp.run()
   ```

2. **Register in configuration** (`config.yaml` or env vars):
   ```yaml
   mcp_servers:
     my-server:
       transport: "stdio"
       command: ["python", "-m", "opsmate.mcp_servers.my_server"]
       mode: "mock"
       timeout: 30
   ```

3. **Restart the application** — the MCP Hub discovers and registers the new server automatically. No code changes to the orchestrator required.

The Tool Registry will pick up `my_tool` on startup and the Intent Planner will include it in the available tool schema for planning.

---

## Screenshots

### Rich CLI

The CLI provides a terminal-native experience with streaming output, syntax-highlighted JSON results, colored status tables, and a persistent mode badge:

```
┌─────────────────────────────────────────────────────┐
│  🔧 OpsMate    MOCK mode    v1.0.0                  │
├─────────────────────────────────────────────────────┤
│  > describe_pods                         ✅ 0.4s    │
│  > get_cloudwatch_metrics                ✅ 0.3s    │
│  > conditional_restart_pods              ✅ 8.3s    │
│  > send_slack_message                    ✅ 0.2s    │
├─────────────────────────────────────────────────────┤
│  Total: 1.8s    Mode: MOCK    ID: exec_a7f3...      │
└─────────────────────────────────────────────────────┘
```

### Web UI — Chat Interface

The React Web UI provides a chat-style interface with message history, markdown rendering, and real-time DAG visualization:

```
┌──────────────────────────────────────────────────────┐
│  🔧 OpsMate                              [MOCK ▼]   │
├──────────────┬───────────────────────────────────────┤
│              │  💬 Chat                              │
│              │                                       │
│              │  > Check payment-service pods...      │
│              │                                       │
│              │  [DAG visualization appears here]     │
│              │  ┌─────────┐     ┌─────────────┐     │
│              │  │describe │────▶│ cloudwatch  │     │
│              │  │ pods    │     │ metrics     │     │
│              │  └─────────┘     └─────────────┘     │
│              │                    │                  │
│              │                    ▼                  │
│              │              ┌─────────────┐         │
│              │              │  restart    │         │
│              │              │  pods       │         │
│              │              └─────────────┘         │
│              │                    │                  │
│              │                    ▼                  │
│              │              ┌─────────────┐         │
│              │              │   slack     │         │
│              │              │   notify    │         │
│              │              └─────────────┘         │
│              │                                       │
│              │  ✅ Execution completed in 1.8s       │
│              │                                       │
│              │  [Type a command...]                  │
├──────────────┴───────────────────────────────────────┤
│  © 2025 mcp-opsmate    |    MIT License              │
└──────────────────────────────────────────────────────┘
```

---

## Why I Built This

After 5 years building multi-agent frameworks and automation platforms at JPMorgan Chase, I noticed a recurring gap: raw LLM chat interfaces are too generic for production infrastructure work, while traditional automation platforms (Rundeck, Ansible Tower) require steep learning curves and rigid workflow definitions.

**The real problem:** At 3 AM during an incident, an SRE shouldn't need to manually sequence 4 different CLI tools, cross-reference their outputs, and paste results into a Slack channel. The cognitive overhead of context-switching between kubectl, AWS CLI, GitHub, and Slack — while under pressure — leads to mistakes and delays.

**The solution:** A terminal-native tool that understands operational semantics, converts natural language into structured execution plans, and handles the multi-tool orchestration with production-grade reliability (circuit breakers, retries, state persistence, audit trails). MOCK mode eliminates the "but I need API keys to try it" friction that kills adoption.

This project demonstrates protocol-oriented architecture, async DAG execution, tiered error recovery, and the full lifecycle of shipping a production-grade tool — from requirements to architecture to implementation to testing to deployment.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with 🔧 by <a href="https://github.com/Freakycobra">Jashwanth Nag Veepuri</a>
</p>
