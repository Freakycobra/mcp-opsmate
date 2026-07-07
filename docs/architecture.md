# mcp-opsmate — Infrastructure Automation MCP Terminal

## Architecture Specification

**Version:** 1.0  
**Author:** Jashwanth Nag Veepuri  
**Date:** 2025-06-01  
**Status:** Draft  

---

## 1. System Overview

OpsMate is built as a layered, event-driven architecture with clear separation between the orchestration engine (domain logic), transport adapters (CLI, Web UI, API), and external tool integrations (MCP servers). The core design principle is **protocol-oriented decoupling**: the orchestrator engine communicates with all tools exclusively through the MCP protocol, treating every MCP server as an interchangeable capability provider. This enables the "new MCP server in <50 lines" extensibility target and ensures that the core engine has no direct dependencies on any external API.

The architecture follows a **command-query separation** pattern for the execution lifecycle. Commands (write operations) flow through the full state-machine-persistence pipeline; Queries (read operations) may bypass persistence for performance if no side effects are anticipated. All operations are traced with a single `execution_id` that propagates through every layer, enabling end-to-end observability.

### 1.1 High-Level Architecture Diagram

```mermaid
graph TB
    subgraph "Client Layer"
        CLI["CLI (Rich TUI)<br/>opsmate-cli"]
        WEB["Web UI (React 18)<br/>opsmate-web"]
    end

    subgraph "Transport Layer"
        WS["WebSocket Handler<br/>/ws/executions"]
        REST["REST API Router<br/>FastAPI"]
        SSE["SSE Stream<br/>/stream/{exec_id}"]
    end

    subgraph "Orchestrator Engine (FastAPI + asyncio)"
        direction TB
        IC["Intent Classifier<br/>GPT-4o + regex"]
        IP["Intent Planner<br/>DAG Builder"]
        SE["Step Executor<br/>asyncio.TaskGroup"]
        SM["State Manager<br/>PostgreSQL + Pydantic"]
        ERH["Error Recovery Handler<br/>Retry + Circuit Breaker"]
        AUTH["Auth Middleware<br/>API Key / Bearer Token"]
    end

    subgraph "MCP Server Hub"
        MGR["MCP Client Manager<br/>stdio + SSE transports"]
        TD["Tool Registry<br/>Dynamic Discovery + Cache"]
        MC["Mock Controller<br/>Mode Router"]
    end

    subgraph "MCP Servers"
        S1["tavily-search"]
        S2["github"]
        S3["slack"]
        S4["jira"]
        S5["aws-ecs"]
        S6["postgres-db"]
        S7["calculator"]
    end

    subgraph "Data Layer"
        PG[("PostgreSQL<br/>Execution State")]
        REDIS[("Redis<br/>Circuit Breaker + Cache")]
    end

    subgraph "External APIs (LIVE Mode)"
        EXT1["Tavily API"]
        EXT2["GitHub API"]
        EXT3["Slack Webhook"]
        EXT4["Jira Cloud API"]
        EXT5["AWS APIs<br/>(LocalStack in MOCK)"]
        EXT6["PostgreSQL<br/>(Docker in MOCK)"]
    end

    CLI -->|"HTTP + Bearer"| REST
    WEB -->|"HTTP + Bearer"| REST
    WEB -->|"WebSocket"| WS

    REST --> AUTH
    WS --> AUTH
    AUTH --> IC
    AUTH --> SM

    IC --> IP
    IP --> SE
    SE --> ERH
    SE --> SM
    ERH --> MGR
    SM --> PG

    MGR --> TD
    MGR --> MC
    MC --> S1 & S2 & S3 & S4 & S5 & S6 & S7

    S1 --> EXT1
    S2 --> EXT2
    S3 --> EXT3
    S4 --> EXT4
    S5 --> EXT5
    S6 --> EXT6
    S7 -->|"local computation"| S7

    ERH -.->|"state queries"| REDIS
    MGR -.->|"circuit state"| REDIS

    style Orchestrator Engine fill:#e1f5fe
    style MCP Server Hub fill:#fff3e0
    style Data Layer fill:#e8f5e9
```

### 1.2 Design Principles

| Principle | Rationale | Manifestation |
|---|---|---|
| **MCP-First** | Avoid tight coupling to any external API; treat all tools as MCP capabilities. | Core engine imports only `mcp` SDK; zero direct AWS/GitHub/Jira client imports. |
| **State Machine Explicitness** | Every execution has a known, persisted state; no implicit execution contexts. | PostgreSQL-backed state machine with 6 states; all transitions logged. |
| **Fail-Safe Defaults** | System defaults to the safest, least-destructive configuration. | MOCK mode default; auto-approve disabled; all write operations require confirmation. |
| **Observability by Design** | Every operation generates traceable, structured output; never an afterthought. | `execution_id` propagated through all layers; OpenTelemetry spans; Prometheus metrics. |
| **Progressive Disclosure** | Simple commands work immediately; complex capabilities available when needed. | Single-tool commands auto-execute; multi-step plans require confirmation; advanced features behind flags. |

---

## 2. Component Breakdown

### 2.1 Orchestrator Engine (FastAPI Application)

The Orchestrator Engine is the central FastAPI application that coordinates all components. It is structured as a modular monolith with internal package boundaries that could later be extracted into separate services if scale demands.

```mermaid
graph LR
    subgraph "FastAPI App (opsmate.api)"
        API["api/main.py<br/>App Factory + Lifespan"]
        R1["api/routes/commands.py"]
        R2["api/routes/executions.py"]
        R3["api/routes/admin.py"]
        R4["api/routes/health.py"]
        MW["api/middleware/<br/>auth.py + logging.py + cors.py"]
    end

    subgraph "Core Domain (opsmate.core)"
        CORE1["core/models.py<br/>Pydantic Schemas"]
        CORE2["core/engine.py<br/>Orchestrator"]
        CORE3["core/state_machine.py<br">"State Transitions"]
        CORE4["core/config.py<br/>Pydantic-Settings"]
    end

    subgraph "Services (opsmate.services)"
        SV1["services/intent.py<br/>Classifier + Planner"]
        SV2["services/executor.py<br/>Step Runner"]
        SV3["services/recovery.py<br/>Error Handler"]
        SV4["services/audit.py<br/>Logger"]
    end

    subgraph "Infrastructure (opsmate.infra)"
        INF1["infra/mcp_hub.py<br/>Client Manager"]
        INF2["infra/database.py<br/>PostgreSQL"]
        INF3["infra/cache.py<br/>Redis"]
        INF4["infra/llm.py<br/>OpenAI Client"]
    end

    API --> R1 & R2 & R3 & R4
    R1 & R2 & R3 --> MW
    MW --> CORE2
    CORE2 --> SV1 & SV2 & SV3 & SV4
    SV1 --> INF4
    SV2 --> INF1
    SV3 --> INF1 & INF3
    SV4 --> INF2
    CORE2 --> CORE3
    CORE3 --> INF2

    style Core Domain fill:#e1f5fe
```

#### 2.1.1 Core Models (`core/models.py`)

The data model hierarchy uses Pydantic v2 for validation, serialization, and OpenAPI schema generation. Key models:

| Model | Purpose | Key Fields |
|---|---|---|
| `CommandRequest` | User command input | `text: str`, `auto_approve: bool`, `metadata: dict` |
| `ExecutionPlan` | Generated DAG | `steps: list[PlanStep]`, `dependencies: dict[str, list[str]]`, `estimated_duration_ms: int` |
| `PlanStep` | Individual step | `id: str`, `tool_name: str`, `server: str`, `input_schema: dict`, `output_schema: dict`, `critical: bool`, `condition: str \| None` |
| `ExecutionState` | Persisted state | `execution_id: UUID`, `status: ExecutionStatus`, `plan: ExecutionPlan`, `results: dict[str, StepResult]`, `context: ExecutionContext` |
| `StepResult` | Step outcome | `step_id: str`, `status: StepStatus`, `output: Any`, `started_at: datetime`, `completed_at: datetime \| None`, `error: StepError \| None` |
| `ExecutionContext` | Shared context | `variables: dict[str, Any]`, `metadata: dict`, `secrets_redacted: bool` |
| `StepError` | Error details | `classification: ErrorType`, `message: str`, `retryable: bool`, `attempt_count: int` |

#### 2.1.2 Configuration (`core/config.py`)

Configuration uses Pydantic-Settings with layered resolution:

```yaml
# Resolution order (later overrides earlier):
# 1. Default values in code
# 2. config.yaml file
# 3. Environment variables (OPS_MATE_* prefix)
# 4. CLI flags

app:
  name: "mcp-opsmate"
  version: "1.0.0"
  execution_mode: "mock"          # global default: mock | live | mixed
  auto_approve: false
  max_concurrent_steps: 10
  plan_confirmation_required: true

llm:
  provider: "openai"
  model: "gpt-4o"
  api_key: "${OPENAI_API_KEY}"     # env var interpolation
  temperature: 0.2                 # low for deterministic planning
  max_tokens: 4096
  planning_timeout_ms: 5000

mcp_servers:
  tavily-search:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.tavily"]
    mode: "live"                   # override global mock default
    timeout: 30
    env:
      TAVILY_API_KEY: "${TAVILY_API_KEY}"

  github:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.github"]
    mode: "live"
    env:
      GITHUB_PAT: "${GITHUB_PAT}"

  slack:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.slack"]
    mode: "live"
    env:
      SLACK_WEBHOOK_URL: "${SLACK_WEBHOOK_URL}"

  jira:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.jira"]
    mode: "live"
    env:
      JIRA_URL: "${JIRA_URL}"
      JIRA_EMAIL: "${JIRA_EMAIL}"
      JIRA_API_TOKEN: "${JIRA_API_TOKEN}"

  aws-ecs:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.aws_ecs"]
    mode: "mock"                   # default to mock; requires AWS creds for live
    env:
      AWS_REGION: "${AWS_REGION:-us-east-1}"

  postgres-db:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.postgres"]
    mode: "live"                   # local Docker PostgreSQL
    env:
      DATABASE_URL: "${DATABASE_URL}"

  calculator:
    transport: "stdio"
    command: ["python", "-m", "opsmate.mcp_servers.calculator"]
    mode: "local"                  # always local computation

database:
  url: "${DATABASE_URL:-postgresql+asyncpg://opsmate:opsmate@localhost:5432/opsmate}"
  pool_size: 10
  max_overflow: 20

cache:
  url: "${REDIS_URL:-redis://localhost:6379/0}"
  ttl: 3600

logging:
  level: "INFO"
  format: "json"                   # json | text
  output: "stdout"
```

---

### 2.2 Intent Classifier (`services/intent.py`)

The Intent Classifier is a hybrid system combining regex-based entity extraction with LLM-based semantic classification.

```mermaid
graph LR
    INPUT["Raw Command<br/>e.g., 'Check payment-service pods in EKS, restart if CPU > 80%'"]
    RE["Regex Extractor<br/>Entity Extraction"]
    LLM["LLM Classifier<br/>GPT-4o"]
    MERGE["Result Merger<br/>Conflict Resolution"]
    OUTPUT["Classified Intent<br/>{type, entities, confidence}"]

    INPUT --> RE
    INPUT --> LLM
    RE --> MERGE
    LLM --> MERGE
    MERGE --> OUTPUT

    style LLM fill:#fff3e0
```

**Regex Extractor** handles high-confidence, low-latency extraction for known patterns:
- Service names: matches against entity dictionary with fuzzy matching (Levenshtein distance <= 2)
- Time ranges: "last 2h" → `(now - 2h, now)`, "since yesterday" → `(yesterday_midnight, now)`
- Thresholds: numeric comparisons with operators (`>`, `<`, `>=`, `<=`, `=`)
- Resource identifiers: AWS ARN patterns, Jira ticket IDs (`[A-Z]+-\d+`), Slack channel names

**LLM Classifier** handles semantic understanding:
- Prompt engineering with few-shot examples (8 examples covering all intent categories)
- Structured output via OpenAI JSON mode / function calling
- Temperature 0.2 for reproducibility
- Classification latency target: < 1s for commands < 500 characters

**Result Merger** applies conflict resolution rules:
1. Regex wins on exact pattern matches (regex is deterministic)
2. LLM wins on ambiguous / novel phrasings
3. Confidence < 70% triggers human-in-the-loop clarification

---

### 2.3 Intent Planner (`services/intent.py` — Plan Generation)

The Intent Planner converts a classified intent into an executable DAG.

```mermaid
graph TB
    subgraph "Planning Phase"
        CI["Classified Intent"]
        TM["Template Matcher<br/>5 built-in templates"]
        ZS["Zero-Shot Planner<br/>GPT-4o + tool schemas"]
        TV["Plan Validator<br/>Tool availability check"]
        PR["Plan Refiner<br/>Dependency optimization"]
    end

    CI --> TM
    TM -->|"template matched"| TV
    TM -->|"no template match"| ZS
    ZS --> TV
    TV -->|"valid"| PR
    TV -->|"invalid"| ZS
    PR --> DAG["Execution Plan DAG"]

    style TM fill:#e1f5fe
    style ZS fill:#fff3e0
```

**Template Matcher** (FR-07): Compares classified intent against 5 built-in plan templates:

| Template Name | Trigger Pattern | Steps |
|---|---|---|
| `health-check-and-remediate` | intent contains "check health" + "restart/fix/remediate" | describe → metric → condition → action → notify |
| `incident-response` | intent contains "incident" + "P0/P1/P2" | search_tickets → correlate_ci → draft_update → notify |
| `deployment-validation` | intent contains "deploy" + "verify/validate/check" | get_workflow → check_pods → run_tests → notify |
| `performance-analysis` | intent contains "compare" + "performance/latency/CPU/memory" | query_metrics → calculate_delta → rank → recommend |
| `cost-analysis` | intent contains "cost" + "spend/billing/optimization" | query_usage → calculate_cost → identify_anomalies → recommend |

**Zero-Shot Planner**: When no template matches, the planner uses GPT-4o with:
- System prompt containing all available tool schemas (from Tool Registry)
- User command + classified intent
- Constraint: must output valid DAG with known tool names only
- Temperature 0.2; max 2 retries if output validation fails

**Plan Validator** (FR-08): Validates the generated plan against the Tool Registry:
- Every tool name exists in at least one connected MCP server
- Input/output schemas are compatible (type checking)
- No circular dependencies in the DAG
- All referenced variables are defined (either by user input or by parent step outputs)

**Plan Refiner**: Optimizes the DAG:
- Collapses unnecessary intermediate steps (e.g., single-value passthroughs)
- Reorders independent steps for maximum parallelism
- Adds explicit `critical: true` flags to destructive operations (restart, delete, modify)

---

### 2.4 Step Executor (`services/executor.py`)

The Step Executor manages the actual execution of the DAG using asyncio.

```mermaid
graph TB
    subgraph "Execution Engine"
        DAG["Execution Plan DAG"]
        TS["Topological Sorter<br/>asyncio-compatible"]
        TG["asyncio.TaskGroup<br/>Parallel Step Execution"]
        Q["Result Queue<br">"asyncio.Queue"]
        CB["Circuit Breaker Check<br/>Redis-backed"]
        MCP["MCP Tool Call<br/>Hub Client"]
    end

    DAG --> TS
    TS -->|"ready steps"| TG
    TG -->|"per step"| CB
    CB -->|"CLOSED → proceed"| MCP
    CB -->|"OPEN → fail fast"| Q
    MCP -->|"result"| Q
    Q -->|"notify dependents"| TS
    Q -->|"persist"| PG[("PostgreSQL")]

    style TG fill:#e1f5fe
    style CB fill:#ffebee
```

**Execution Algorithm:**

```python
# Pseudocode — actual implementation uses asyncio.TaskGroup
async def execute_plan(execution_state: ExecutionState) -> ExecutionState:
    dag = execution_state.plan.dependencies
    in_degree = compute_in_degrees(dag)
    completed = {}
    running = set()

    async with asyncio.TaskGroup() as tg:
        # Start with zero-dependency steps
        ready = [step for step, deg in in_degree.items() if deg == 0]
        for step_id in ready:
            tg.create_task(execute_step(step_id, execution_state.context))

        # As steps complete, enqueue their dependents
        while len(completed) < len(dag):
            result = await result_queue.get()
            completed[result.step_id] = result

            for dependent in dag.get(result.step_id, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    # Check conditional execution
                    step = execution_state.plan.get_step(dependent)
                    if step.condition:
                        should_run = evaluate_condition(step.condition, completed)
                        if not should_run:
                            completed[dependent] = StepResult.skipped()
                            continue
                    tg.create_task(execute_step(dependent, execution_state.context))

    return execution_state.with_results(completed)
```

**Key Design Decisions:**
- `asyncio.TaskGroup` (Python 3.11+) provides structured concurrency — if any step fails critically, all running steps are cancelled
- Topological sorting ensures correctness; parallelism achieves the NFR-03 concurrency target
- Each step runs in its own asyncio task with isolated exception handling
- Results are persisted to PostgreSQL after every step completion (FR-21)

---

### 2.5 State Manager (`services/state.py`)

The State Manager handles persistence and retrieval of execution state.

```mermaid
erDiagram
    EXECUTIONS {
        uuid execution_id PK
        varchar status
        jsonb plan
        jsonb results
        jsonb context
        timestamptz created_at
        timestamptz updated_at
        timestamptz completed_at
        varchar execution_mode
        varchar command_text
        float planning_duration_ms
        float total_duration_ms
    }

    STEP_RESULTS {
        uuid id PK
        uuid execution_id FK
        varchar step_id
        varchar status
        jsonb output
        timestamptz started_at
        timestamptz completed_at
        jsonb error
        int attempt_count
    }

    AUDIT_LOGS {
        uuid id PK
        uuid execution_id FK
        varchar action
        jsonb details
        timestamptz timestamp
        varchar user_id
    }

    EXECUTIONS ||--o{ STEP_RESULTS : contains
    EXECUTIONS ||--o{ AUDIT_LOGS : generates
```

**Persistence Strategy:**
- **Write pattern:** After every step completion, a diff-based update is written to PostgreSQL. Only changed fields are updated to minimize write volume.
- **Read pattern:** Execution state is loaded by `execution_id` with all related step results (eager loading via SQLAlchemy `selectinload`).
- **Cleanup:** Daily cron job archives executions older than 30 days to compressed JSON files and deletes database records (FR-24).

**State Transitions:** See Section 4 for the full state machine diagram.

---

### 2.6 Error Recovery Handler (`services/recovery.py`)

The Error Recovery Handler implements a multi-tier error handling strategy.

```mermaid
graph TB
    ERROR["Tool Call Error"]
    CLASS["Error Classifier"]

    subgraph "Retry Branch"
        R1["Attempt 1<br/>immediate"]
        R2["Attempt 2<br/>backoff 2s"]
        R3["Attempt 3<br/>backoff 4s"]
    end

    subgraph "Circuit Breaker Branch"
        CB1["Failure Count++"]
        CB2["Count >= 5?<br/>OPEN circuit"]
        CB3["Fail Fast<br/>for 30s"]
        CB4["Half-Open Probe"]
    end

    subgraph "Escalation Branch"
        H1["Critical Step?<br/>OR confidence < 70%?"]
        H2["Human-in-the-Loop Prompt<br/>5min timeout"]
        H3["Continue / Abort / Modify"]
    end

    ERROR --> CLASS
    CLASS -->|"TRANSIENT"| R1
    R1 -->|"fail"| R2
    R2 -->|"fail"| R3
    R3 -->|"fail"| CB1
    CLASS -->|"NON-TRANSIENT"| CB1
    CB1 --> CB2
    CB2 -->|"YES"| CB3
    CB3 --> CB4
    CB2 -->|"NO"| H1
    R1 & R2 & R3 -->|"success"| DONE["Resume Execution"]
    CB4 -->|"success"| DONE
    CB4 -->|"fail"| CB3
    H1 -->|"YES"| H2
    H2 --> H3
    H3 -->|"Continue"| DONE
    H3 -->|"Abort"| ABORT["Execution FAILED"]
    H1 -->|"NO<br/>non-critical"| SKIP["Skip + Degraded Output"]

    style Retry Branch fill:#e8f5e9
    style Circuit Breaker Branch fill:#ffebee
    style Escalation Branch fill:#fff3e0
```

**Error Classification Rules:**

| Error Pattern | Classification | Retryable | Circuit Breaker Increment |
|---|---|---|---|
| `TimeoutError`, `asyncio.TimeoutError` | TRANSIENT | Yes | Yes |
| `ConnectionResetError`, `BrokenPipeError` | TRANSIENT | Yes | Yes |
| HTTP 429 (Rate Limited) | TRANSIENT | Yes (respect Retry-After) | Yes |
| HTTP 500, 502, 503, 504 | TRANSIENT | Yes | Yes |
| HTTP 400, 401, 403, 404 | PERMANENT | No | Yes |
| MCP tool not found | CONFIGURATION | No | No |
| Schema validation failure | CONFIGURATION | No | No |
| LLM planning failure | TRANSIENT | Yes (max 2 retries) | No |

**Circuit Breaker Implementation (Redis-backed):**

```python
class CircuitBreaker:
    """Redis-backed circuit breaker for MCP servers."""

    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT = 30  # seconds
    HALF_OPEN_MAX_CALLS = 1

    async def call(self, server_name: str, operation: Callable) -> Any:
        state = await self._get_state(server_name)

        if state == CircuitState.OPEN:
            if await self._recovery_timeout_elapsed(server_name):
                state = CircuitState.HALF_OPEN
                await self._set_state(server_name, state)
            else:
                raise CircuitBreakerOpenError(f"{server_name} circuit is OPEN")

        if state == CircuitState.HALF_OPEN:
            if await self._half_open_calls_exceeded(server_name):
                raise CircuitBreakerOpenError(f"{server_name} half-open limit reached")

        try:
            result = await operation()
            await self._record_success(server_name)
            return result
        except Exception as e:
            await self._record_failure(server_name)
            raise
```

---

### 2.7 MCP Server Hub (`infra/mcp_hub.py`)

The MCP Server Hub is the abstraction layer that manages all MCP server connections, tool discovery, and mode-aware routing.

```mermaid
graph LR
    subgraph "MCP Hub"
        MC["MCPClientManager"]
        TR["ToolRegistry"]
        MR["ModeRouter"]
    end

    subgraph "Transports"
        STDIO["stdio<br/>subprocess"]
        SSE["SSE<br/>HTTP/httpx"]
    end

    subgraph "Mock Layer"
        MF["MockFactory<br/>seeded faker"]
        ML["LatencyInjector<br/>50-200ms"]
    end

    MC --> STDIO & SSE
    MC --> TR
    TR --> MR
    MR -->|"mock mode"| MF
    MF --> ML
    MR -->|"live mode"| STDIO & SSE

    style Mock Layer fill:#fff3e0
```

**MCP Client Manager:**
- Manages the lifecycle of MCP client connections (stdio and SSE transports)
- Reconnections with exponential backoff (max 5 attempts, then circuit breaker triggers)
- Health checks every 30 seconds via `mcp.list_tools()` ping

**Tool Registry:**
- Discovers all available tools from connected MCP servers at startup
- Caches tool schemas (name, description, input schema, output schema, server source)
- Provides tool lookup by name (with server prefix disambiguation: `aws-ecs/describe_pods`)
- Refreshes on explicit `/admin/tools/refresh` call or MCP server reconnection

**Mode Router:**
- Resolves the execution mode per MCP server at call time
- In MOCK mode: routes to Mock Factory instead of real transport
- In MIXED mode: checks per-server configuration to determine routing
- Mode resolution is logged and included in the execution audit trail

---

### 2.8 CLI Interface (`opsmate-cli`)

The CLI is a standalone Python package (`opsmate-cli`) built on the Rich library, communicating with the FastAPI backend via HTTP.

```mermaid
graph TB
    subgraph "CLI Process"
        PARSE["Argument Parser<br/>click/Typer"]
        AUTH["Auth Handler<br/>~/.opsmate/credentials"]
        RENDER["Rich Renderer<br/>Live Display"]
        STREAM["SSE Consumer<br/>httpx.SSE"]
    end

    subgraph "Display Components"
        PANEL["Plan Panel<br/>Steps + Dependencies"]
        TABLE["Result Tables<br/>Syntax Highlighted"]
        SPINNER["Progress Spinners<br/>Per-step status"]
        BADGE["Mode Badge<br/>MOCK/LIVE/MIXED"]
    end

    PARSE --> AUTH
    AUTH -->|"POST /commands"| API["FastAPI Backend"]
    API -->|"SSE stream"| STREAM
    STREAM --> RENDER
    RENDER --> PANEL & TABLE & SPINNER & BADGE

    style Display Components fill:#e1f5fe
```

**Key CLI Features:**
- **Streaming output:** Consumes Server-Sent Events from `/stream/{execution_id}`; renders each event type (plan_generated, step_started, step_completed, step_failed, execution_completed) with appropriate Rich component
- **Plan confirmation:** Interrupts stream to display plan DAG and prompt for confirmation; resumes or aborts based on user input
- **Persistent history:** `~/.opsmate/history` file with readline-style recall (up/down arrows)
- **Command flags:** `--mode`, `--auto-approve`, `--output json|table|markdown`, `--verbose`, `--execution-id`, `--config`

---

### 2.9 Web UI (`opsmate-web`)

The Web UI is a React 18 + TypeScript application built with Vite, communicating with the backend via REST API and WebSocket.

```mermaid
graph TB
    subgraph "React App"
        ROUTER["React Router<br/>/chat /history /dashboard /admin"]
        AUTH["Auth Context<br/>API Key in localStorage"]
        API["API Client<br/>axios + zod validation"]
        WS["WebSocket Client<br/>native WebSocket"]
    end

    subgraph "Pages"
        CHAT["Chat Page<br/>Message Thread + Input"]
        HIST["History Page<br/>Filter + Search + Detail"]
        DASH["Dashboard Page<br/>Metrics + Charts"]
        ADMIN["Admin Page<br/>Mode Switch + Health"]
    end

    subgraph "Shared Components"
        DAG["DAG Visualizer<br/>ReactFlow"]
        MODE["Mode Indicator<br/>Persistent Header"]
        TOAST["Toast Notifications<br">"Success/Error/Warning"]
    end

    ROUTER --> CHAT & HIST & DASH & ADMIN
    CHAT --> DAG
    CHAT & HIST & DASH & ADMIN --> MODE
    API -->|"HTTP"| FastAPI
    WS -->|"WebSocket"| FastAPI
    CHAT --> WS
    HIST --> API
    DASH --> API
    ADMIN --> API

    style Shared Components fill:#e1f5fe
```

**Technology Choices:**
- **React 18** with hooks and functional components — no class components
- **State management:** React Context + `useReducer` for global state (auth, mode); no external state library needed for v1.0 scope
- **Styling:** Tailwind CSS for utility-first styling; shadcn/ui component primitives
- **Charts:** Recharts for dashboard metrics (lightweight, React-native)
- **DAG visualization:** ReactFlow for interactive plan graphs
- **HTTP client:** Axios with interceptors for auth header injection and error handling
- **Validation:** Zod for runtime API response validation

---

## 3. Data Flow

### 3.1 Full Request Lifecycle (Sequence Diagram)

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant CLI as CLI / Web UI
    participant API as FastAPI Router
    participant AUTH as Auth Middleware
    participant IC as Intent Classifier
    participant IP as Intent Planner
    participant SE as Step Executor
    participant SM as State Manager
    participant ERH as Error Recovery
    participant MH as MCP Hub
    participant PG as PostgreSQL
    participant RD as Redis
    participant MCP as MCP Server

    U->>CLI: Type command
    CLI->>API: POST /commands {text, auto_approve}
    API->>AUTH: Validate API key
    AUTH-->>API: Authenticated

    API->>SM: create_execution(command)
    SM->>PG: INSERT executions
    PG-->>SM: execution_id = uuid
    SM-->>API: ExecutionState(PENDING)

    API->>IC: classify(command)
    IC-->>API: Intent{type, entities, confidence}

    alt confidence < 0.7
        API-->>CLI: 422 Clarification required
        U->>CLI: Provide clarification
        CLI->>API: POST /commands (refined)
    end

    API->>IP: build_plan(intent)
    IP->>MH: get_available_tools()
    MH-->>IP: ToolRegistry[tools]
    IP-->>API: ExecutionPlan{DAG}

    API->>SM: transition_planning → awaiting_confirmation
    SM->>PG: UPDATE status

    alt not auto_approve
        API-->>CLI: ExecutionPlan for confirmation
        U->>CLI: Approve plan
        CLI->>API: POST /executions/{id}/approve
    end

    API->>SM: transition_executing
    SM->>PG: UPDATE status

    loop For each step in topological order
        API->>SE: execute_step(step_id)
        SE->>ERH: check_circuit_breaker(server)
        ERH->>RD: GET circuit_state
        RD-->>ERH: CLOSED

        SE->>MH: call_tool(server, tool, args)
        MH->>MCP: MCP tool call
        MCP-->>MH: Tool result
        MH-->>SE: Result

        alt step fails
            SE->>ERH: handle_error(error)
            ERH->>ERH: classify_error(error)

            alt TRANSIENT
                ERH->>SE: retry with backoff
            else CIRCUIT OPEN
                ERH->>RD: SET circuit=OPEN
            else CRITICAL
                ERH-->>CLI: Human-in-the-loop prompt
                U->>CLI: Continue/Abort
            end
        end

        SE->>SM: persist_step_result(result)
        SM->>PG: INSERT/UPDATE step_results
        SM-->>SE: OK

        SE-->>API: StepResult
        API-->>CLI: SSE event: step_completed
    end

    API->>SM: transition_completed
    SM->>PG: UPDATE status, completed_at
    SM-->>API: Final ExecutionState

    API-->>CLI: SSE event: execution_completed
    CLI-->>U: Render final output
```

---

## 4. State Machine

### 4.1 Execution Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING : Command received
    PENDING --> PLANNING : Intent classification starts
    PLANNING --> AWAITING_CONFIRMATION : Plan generated (multi-step)
    PLANNING --> EXECUTING : Plan generated (single-step, auto-approve)
    PLANNING --> FAILED : Planning error (irrecoverable)
    AWAITING_CONFIRMATION --> EXECUTING : User approves
    AWAITING_CONFIRMATION --> CANCELLED : User rejects
    AWAITING_CONFIRMATION --> CANCELLED : Timeout (5 min)
    EXECUTING --> COMPLETED : All steps succeed
    EXECUTING --> PAUSED : Human-in-the-loop escalation
    EXECUTING --> FAILED : Critical step fails + no recovery
    PAUSED --> EXECUTING : User continues
    PAUSED --> FAILED : User aborts
    PAUSED --> FAILED : Timeout (5 min)
    COMPLETED --> [*]
    FAILED --> [*]
    CANCELLED --> [*]

    note right of PENDING
        State persisted to PostgreSQL
        after every transition
    end note

    note right of EXECUTING
        Step results persisted
        after each step completion
        Graceful shutdown: finish
        in-flight steps, persist,
        resume on restart
    end note
```

### 4.2 State Transition Table

| Current State | Event | Next State | Action | Side Effects |
|---|---|---|---|---|
| `PENDING` | `classify_start` | `PLANNING` | Begin intent classification | Log audit entry |
| `PLANNING` | `plan_generated` | `AWAITING_CONFIRMATION` | Present plan to user | SSE event emitted |
| `PLANNING` | `single_step_auto` | `EXECUTING` | Auto-approve single-step | Skip confirmation |
| `PLANNING` | `plan_error` | `FAILED` | Log error, notify user | Audit log: error details |
| `AWAITING_CONFIRMATION` | `user_approve` | `EXECUTING` | Begin step execution | Persist approval timestamp |
| `AWAITING_CONFIRMATION` | `user_reject` | `CANCELLED` | Clean up, notify user | Audit log: user rejection |
| `AWAITING_CONFIRMATION` | `timeout` | `CANCELLED` | Auto-cancel | Audit log: timeout |
| `EXECUTING` | `all_steps_complete` | `COMPLETED` | Compile final output | Update completed_at |
| `EXECUTING` | `critical_step_fail` | `PAUSED` | Human-in-the-loop prompt | SSE: escalation event |
| `EXECUTING` | `irrecoverable_error` | `FAILED` | Log failure, notify user | Circuit breaker may trigger |
| `PAUSED` | `user_continue` | `EXECUTING` | Resume from current step | Log user decision |
| `PAUSED` | `user_abort` | `FAILED` | Mark failed | Audit log: user abort |
| `PAUSED` | `timeout` | `FAILED` | Auto-abort | Audit log: timeout abort |
| Any | `sigterm_received` | (persist) | Finish in-flight, persist | SIGTERM handler |
| Any | `startup_resume` | `EXECUTING` | Load persisted state | Find incomplete executions |

---

## 5. Error Handling Strategy

### 5.1 Tiered Error Handling

OpsMate implements a four-tier error handling strategy, with each tier handling progressively more severe failure modes:

| Tier | Scope | Mechanism | Trigger | Recovery Action |
|---|---|---|---|---|
| **T1: Retry** | Individual tool call | Exponential backoff, 3 attempts | Transient failures (timeout, rate limit, 5xx) | Automatic; no user involvement |
| **T2: Circuit Breaker** | MCP server | Redis-backed state machine | 5 consecutive failures on a server | Fail-fast for 30s; half-open probe |
| **T3: Degraded Execution** | Execution plan | Non-critical step skip | Non-critical step failure after retries | Continue with partial results; flag omissions |
| **T4: Human Escalation** | Full execution | Interactive prompt (CLI) / modal (Web) | Critical step failure; destructive op failure; confidence < 70% | User chooses: continue, abort, or modify plan |

### 5.2 Error Classification Engine

```python
class ErrorClassifier:
    """Classifies errors into actionable categories for tiered handling."""

    TRANSIENT_EXCEPTIONS = (
        asyncio.TimeoutError,
        ConnectionResetError,
        BrokenPipeError,
    )

    TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
    PERMANENT_STATUS_CODES = {400, 401, 403, 404, 405}

    def classify(self, exception: Exception, server_name: str, tool_name: str) -> ErrorClassification:
        # 1. Check exception type
        if isinstance(exception, self.TRANSIENT_EXCEPTIONS):
            return ErrorClassification.TRANSIENT

        # 2. Check HTTP status codes
        if hasattr(exception, 'status_code'):
            if exception.status_code in self.TRANSIENT_STATUS_CODES:
                return ErrorClassification.TRANSIENT
            if exception.status_code in self.PERMANENT_STATUS_CODES:
                return ErrorClassification.PERMANENT

        # 3. Check MCP-specific errors
        if isinstance(exception, MCPToolNotFoundError):
            return ErrorClassification.CONFIGURATION
        if isinstance(exception, MCPSchemaValidationError):
            return ErrorClassification.CONFIGURATION

        # 4. Default: treat unknown errors as TRANSIENT (fail-safe)
        return ErrorClassification.TRANSIENT
```

### 5.3 Partial Failure Recovery

When a non-critical step fails after all retries:

1. The step is marked as `FAILED` in the execution state
2. The failure is logged with full context (step_id, error classification, attempt history)
3. Dependent steps are evaluated: if a dependent step's condition requires the failed step's output, it is skipped with a `SKIPPED_DUE_TO_DEPENDENCY` status
4. The execution continues with remaining independent steps
5. The final output includes a "Degraded Results" section listing failed steps and their impact

### 5.4 Human-in-the-Loop Escalation

Escalation is triggered when any of the following conditions are met:

| Condition | Rationale | User Options |
|---|---|---|
| Critical step fails after all retries | Data loss or operational risk if proceeding without the step | Retry now, Skip step, Abort execution |
| Destructive operation (restart, delete) fails mid-execution | Partial remediation may leave system in inconsistent state | Rollback (if supported), Continue, Abort |
| Plan confidence < 70% | High risk of incorrect action | Review plan, Edit plan, Abort |
| Circuit breaker open for required MCP server | Cannot proceed with degraded capability | Wait and retry, Abort, Switch to mock |

The escalation prompt includes:
- **What failed:** Step name, MCP server, tool name, error message
- **Impact:** Which downstream steps are affected
- **Options:** Available actions with risk assessment
- **Timeout:** 5-minute default auto-abort timer

---

## 6. Mock vs Live Architecture

### 6.1 Mode Resolution at Runtime

```mermaid
graph TB
    CALL["Tool Call Request<br/>{server, tool, args}"]
    RESOLVE["Mode Resolver"]

    subgraph "Resolution Logic"
        G["Global Mode<br/>EXECUTION_MODE env"]
        S["Server Override<br/>mcp_servers[server].mode"]
        C["Call Override<br/>mode param in request"]
    end

    CALL --> RESOLVE
    RESOLVE --> C
    C -->|"explicit"| ROUTE
    C -->|"default"| S
    S -->|"override set"| ROUTE
    S -->|"default"| G
    G --> ROUTE["Route to<br/>Mock or Live"]

    ROUTE -->|"LIVE"| LIVE["Real MCP Transport<br/>stdio / SSE"]
    ROUTE -->|"MOCK"| MOCK["Mock Factory<br/>Seeded Faker"]
    ROUTE -->|"MIXED"| MIXED["Per-server routing"]

    style MOCK fill:#fff3e0
    style LIVE fill:#e8f5e9
```

**Resolution Priority:** `Per-call override` > `Server config override` > `Global default`

### 6.2 Mock Factory Architecture

The Mock Factory generates realistic synthetic data without external API calls.

```mermaid
graph LR
    subgraph "Mock Factory"
        MF["MockFactory"]
        SD["Seed Manager<br/>deterministic"]
        SM["Schema Matcher<br/>Pydantic models"]
        LI["Latency Injector<br/>50-200ms"]
    end

    subgraph "Mock Implementations"
        M1["tavily_mock.py"]
        M2["github_mock.py"]
        M3["slack_mock.py"]
        M4["jira_mock.py"]
        M5["aws_ecs_mock.py"]
        M6["postgres_mock.py"]
        M7["calculator.py<br/>(always local)"]
    end

    MF --> SD & SM & LI
    MF --> M1 & M2 & M3 & M4 & M5 & M6 & M7

    style Mock Factory fill:#fff3e0
```

**Mock Implementation Principles:**
1. **Schema parity:** Every mock response validates against the same Pydantic model as the live response (NFR-23)
2. **Determinism:** Same seed (derived from command text hash) produces identical outputs for reproducible testing
3. **Realism:** Mock data uses Faker library with infrastructure-relevant providers (AWS ARNs, Kubernetes pod names, GitHub PR numbers)
4. **Latency injection:** Configurable artificial delay (default 50-200ms) to simulate real API latency
5. **Error simulation:** Configurable error rate (default 0%) for testing error handling paths

**Example Mock Data Generation:**

```python
class AWSECSMock:
    """Mock implementation of AWS ECS/EKS operations."""

    def __init__(self, seed: int):
        self.faker = Faker()
        self.faker.seed_instance(seed)

    async def describe_pods(self, namespace: str, service: str) -> list[PodStatus]:
        await self._inject_latency()
        pod_count = self.faker.random_int(min=2, max=10)
        return [
            PodStatus(
                name=f"{service}-{self.faker.hexify('^^^^^^^')}-{i}",
                namespace=namespace,
                status=self.faker.random_element(["Running", "Running", "Running", "Pending", "CrashLoopBackOff"]),
                restarts=self.faker.random_int(min=0, max=5),
                cpu_percent=self.faker.random_int(min=5, max=95),
                memory_percent=self.faker.random_int(min=10, max=85),
                age=f"{self.faker.random_int(min=1, max=72)}h",
            )
            for i in range(pod_count)
        ]
```

### 6.3 Live Mode Credential Flow

```mermaid
graph LR
    ENV["Environment Variables<br/>.env file (gitignored)"]
    PS["Pydantic-Settings<br/>Validation + Loading"]
    CFG["Runtime Config<br/>Read-only after startup"]
    MCP["MCP Server Process<br/>env vars passed via stdio"]
    API["External API<br/>Tavily/GitHub/etc."]

    ENV -->|"${VAR_NAME}"| PS
    PS -->|"Validated settings"| CFG
    CFG -->|"Per-server env dict"| MCP
    MCP -->|"HTTP request with auth"| API

    style ENV fill:#ffebee
```

**Security Rules:**
- Credentials are loaded once at startup via Pydantic-Settings
- After startup, config is read-only (immutable settings object)
- Credentials are passed to MCP server processes via environment variables (stdio transport) or injected into HTTP headers (SSE transport)
- The orchestrator never logs, stores, or returns credential values
- Redaction middleware strips credentials from all log output using regex patterns

---

## 7. Technology Decisions (ADR Summary)

### ADR-001: FastAPI over Flask/Django

| Aspect | Decision |
|---|---|
| **Decision** | Use FastAPI as the web framework. |
| **Context** | Need async-native framework with automatic OpenAPI generation, request validation, and dependency injection. |
| **Options Considered** | Flask + Flask-SocketIO (not natively async), Django + DRF (too heavyweight), aiohttp (no validation/OpenAPI), FastAPI (async-native, Pydantic integration). |
| **Rationale** | FastAPI provides native `async/await` support (critical for concurrent MCP tool calls), automatic OpenAPI/Swagger docs (reduces documentation burden), and Pydantic v2 integration (shared models between API and business logic). |
| **Trade-offs** | Smaller ecosystem than Flask/Django; fewer third-party extensions. Mitigated by using stdlib `asyncio` and `httpx` for HTTP needs. |
| **Consequences** | Positive: ~40% less boilerplate code for API endpoints. Negative: Team learning curve if unfamiliar with dependency injection patterns. |

### ADR-002: asyncio + TaskGroup over Celery/RQ

| Aspect | Decision |
|---|---|
| **Decision** | Use Python `asyncio` with `TaskGroup` for concurrency; no external task queue. |
| **Context** | Need to execute multiple MCP tool calls concurrently with shared state and dependency ordering. |
| **Options Considered** | Celery + Redis (distributed, but adds infrastructure complexity), RQ (simpler but not async-native), asyncio.TaskGroup (structured concurrency, no external deps). |
| **Rationale** | All MCP tool calls are I/O-bound (HTTP requests), making asyncio ideal. TaskGroup provides structured concurrency with automatic cancellation on failure. No external broker needed for v1.0 single-node deployment. |
| **Trade-offs** | No persistence of in-flight tasks across process restarts (mitigated by State Manager persistence). No horizontal scaling without re-architecture (acceptable for v1.0). |
| **Consequences** | Positive: Zero additional infrastructure; sub-50ms task creation latency. Negative: Limited to single-node execution; long-running tasks block an event loop thread. |

### ADR-003: PostgreSQL over SQLite/MongoDB

| Aspect | Decision |
|---|---|
| **Decision** | Use PostgreSQL for all persistence (execution state, audit logs). |
| **Context** | Need ACID-compliant persistence for execution state with JSON support for flexible schemas. |
| **Options Considered** | SQLite (simple but no concurrent writes), MongoDB (flexible schema but no ACID transactions), PostgreSQL (ACID + JSONB + mature async drivers). |
| **Rationale** | PostgreSQL's JSONB columns provide schema flexibility for execution plans and results while maintaining ACID guarantees. `asyncpg` driver offers best-in-class async performance. Docker Compose provides zero-friction local deployment. |
| **Trade-offs** | Heavier than SQLite for single-user deployments. Mitigated by Docker Compose one-command startup. |
| **Consequences** | Positive: Reliable persistence, complex querying, JSON indexing. Negative: Requires Docker for local development. |

### ADR-004: Rich CLI over Click-only/plain terminal

| Aspect | Decision |
|---|---|
| **Decision** | Use Rich library for the CLI interface. |
| **Context** | Need visually compelling terminal output for portfolio demonstration and practical operational readability. |
| **Options Considered** | Plain print (insufficient for portfolio), Click + colorama (basic colors only), Rich (tables, panels, syntax highlighting, spinners, progress bars). |
| **Rationale** | Rich provides production-quality terminal UI components without additional dependencies (single package). Syntax-highlighted JSON output, tables, and live displays are essential for infrastructure tool credibility. |
| **Trade-offs** | Adds ~50MB to package size. Fallback to plain text for `TERM=dumb` environments required. |
| **Consequences** | Positive: Professional terminal UX; portfolio differentiation. Negative: Windows terminal compatibility testing required. |

### ADR-005: React + Vite over Next.js/Svelte

| Aspect | Decision |
|---|---|
| **Decision** | Use React 18 + TypeScript + Vite for the Web UI. |
| **Context** | Need a modern, fast-building frontend for demonstration and dashboard functionality. |
| **Options Considered** | Next.js (SSR not needed; adds complexity), Svelte (smaller bundle but less ecosystem), React + Vite (standard, fast builds, extensive component libraries). |
| **Rationale** | React's ecosystem (shadcn/ui, ReactFlow, Recharts) provides all needed components without custom development. Vite offers instant HMR and optimized builds. TypeScript ensures type safety shared with backend Pydantic models. |
| **Trade-offs** | Larger bundle size than Svelte; no SSR means SEO is irrelevant (internal tool). |
| **Consequences** | Positive: Rich component ecosystem; rapid development. Negative: 200KB+ bundle size; requires modern browser. |

### ADR-006: OpenAI GPT-4o over Claude/local models

| Aspect | Decision |
|---|---|
| **Decision** | Use OpenAI GPT-4o as the exclusive LLM provider for v1.0. |
| **Context** | Need reliable intent classification and plan generation with structured output support. |
| **Options Considered** | Anthropic Claude (excellent reasoning but different API), local models via Ollama (no API costs but requires GPU, slower), GPT-4o (fast, reliable structured output, well-documented). |
| **Rationale** | GPT-4o's JSON mode and function calling provide deterministic structured output essential for plan generation. Single provider simplifies the codebase. API costs are acceptable for portfolio/demo usage. |
| **Trade-offs** | Vendor lock-in to OpenAI; API costs for production usage. Mitigated by abstracting LLM calls behind `infra/llm.py` interface. |
| **Consequences** | Positive: Reliable structured output; fast planning (< 2s). Negative: Ongoing API costs; data sent to third-party. |

### ADR-007: Docker Compose over Kubernetes/ bare metal

| Aspect | Decision |
|---|---|
| **Decision** | Use Docker Compose as the primary deployment mechanism for v1.0. |
| **Context** | Need zero-friction local deployment for portfolio demonstration and small-team usage. |
| **Options Considered** | Kubernetes (overkill for single-node), bare metal (manual dependency management), Docker Compose (single-node orchestration, simple configuration). |
| **Rationale** | Docker Compose provides one-command startup (`docker compose up`) for the entire stack: FastAPI backend, PostgreSQL, React frontend, and all MCP servers. Perfect for portfolio reviewers who want to run the project in < 5 minutes. |
| **Trade-offs** | No horizontal scaling; single point of failure. Acceptable for v1.0 scope (OS-02). |
| **Consequences** | Positive: Instant deployment; reproducible environments. Negative: Production deployments require additional work (OS-02 addresses this in v2.0). |

---

## 8. Project Structure

```
mcp-opsmate/
├── README.md                          # Project overview, quick start, architecture summary
├── docker-compose.yml                 # Full stack: backend, db, frontend, MCP servers
├── .env.example                       # Template for required environment variables
├── .gitignore
├── Makefile                           # Common commands: test, lint, format, build
│
├── opsmate/                           # Main Python package (backend)
│   ├── __init__.py
│   ├── pyproject.toml                 # Poetry dependencies, scripts entry points
│   ├── Dockerfile
│   │
│   ├── api/                           # FastAPI application
│   │   ├── __init__.py
│   │   ├── main.py                    # App factory, lifespan events, router aggregation
│   │   ├── dependencies.py            # FastAPI dependencies (auth, db session, config)
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py               # API key validation, admin token check
│   │   │   ├── logging.py            # Request/response logging with execution_id
│   │   │   └── cors.py               # CORS configuration for Web UI
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── commands.py           # POST /commands — submit new command
│   │   │   ├── executions.py         # GET /executions, /executions/{id}, /executions/{id}/approve
│   │   │   ├── admin.py              # /admin/mode, /admin/health, /admin/tools/refresh
│   │   │   ├── health.py             # GET /health, GET /metrics (Prometheus)
│   │   │   └── stream.py             # SSE /stream/{execution_id}
│   │   └── websocket/
│   │       ├── __init__.py
│   │       └── handler.py            # WebSocket connection handler for real-time updates
│   │
│   ├── core/                          # Domain models and configuration
│   │   ├── __init__.py
│   │   ├── models.py                  # Pydantic v2 models: Command, ExecutionPlan, ExecutionState, etc.
│   │   ├── config.py                  # Pydantic-Settings configuration with env var loading
│   │   ├── state_machine.py          # Execution state transitions and validation
│   │   ├── constants.py              # Enums, magic numbers, default values
│   │   └── exceptions.py             # Custom exceptions: OpsMateError, PlanningError, etc.
│   │
│   ├── services/                      # Business logic layer
│   │   ├── __init__.py
│   │   ├── intent.py                  # Intent Classifier + Intent Planner (hybrid regex + LLM)
│   │   ├── executor.py               # Step Executor: DAG execution with asyncio.TaskGroup
│   │   ├── recovery.py               # Error Recovery Handler: retry, circuit breaker, escalation
│   │   ├── state.py                  # State Manager: PostgreSQL persistence
│   │   └── audit.py                  # Audit logging: structured JSON logs
│   │
│   ├── infra/                         # Infrastructure adapters
│   │   ├── __init__.py
│   │   ├── mcp_hub.py                # MCP Client Manager, Tool Registry, Mode Router
│   │   ├── database.py               # SQLAlchemy async engine, session management, migrations
│   │   ├── cache.py                  # Redis client wrapper (circuit breaker state)
│   │   ├── llm.py                    # OpenAI client abstraction with retry logic
│   │   └── mock_factory.py           # Mock data generation, latency injection
│   │
│   ├── mcp_servers/                   # Built-in MCP server implementations
│   │   ├── __init__.py
│   │   ├── base.py                    # Abstract base class for MCP servers
│   │   ├── tavily/
│   │   │   ├── __main__.py            # Entry point for stdio transport
│   │   │   ├── server.py             # Tavily search tools (search, answer)
│   │   │   └── mock.py               # Mock implementation with schema parity
│   │   ├── github/
│   │   │   ├── __main__.py
│   │   │   ├── server.py             # GitHub tools (repo_info, workflow_status, pr_checks)
│   │   │   └── mock.py
│   │   ├── slack/
│   │   │   ├── __main__.py
│   │   │   ├── server.py             # Slack tools (send_message, channel_info)
│   │   │   └── mock.py
│   │   ├── jira/
│   │   │   ├── __main__.py
│   │   │   ├── server.py             # Jira tools (search_tickets, create_incident)
│   │   │   └── mock.py
│   │   ├── aws_ecs/
│   │   │   ├── __main__.py
│   │   │   ├── server.py             # AWS tools (describe_pods, get_metrics, restart_service)
│   │   │   └── mock.py
│   │   ├── postgres/
│   │   │   ├── __main__.py
│   │   │   ├── server.py             # PostgreSQL tools (execute_query, get_tables)
│   │   │   └── mock.py
│   │   └── calculator/
│   │       ├── __main__.py
│   │       └── server.py             # Calculator tools (math, date_calc, threshold_check)
│   │
│   └── templates/                     # Plan templates (YAML)
│       ├── health_check_remediate.yaml
│       ├── incident_response.yaml
│       ├── deployment_validation.yaml
│       ├── performance_analysis.yaml
│       └── cost_analysis.yaml
│
├── opsmate-cli/                       # CLI application (separate package)
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── opsmate_cli/
│   │   ├── __init__.py
│   │   ├── main.py                    # Typer/Click entry point
│   │   ├── client.py                  # HTTP client for FastAPI backend
│   │   ├── renderer.py               # Rich-based output rendering
│   │   ├── commands.py               # Command definitions (run, history, status, config)
│   │   ├── interactive.py            # Interactive mode with history and completion
│   │   └── config.py                 # CLI configuration (~/.opsmate/config.yaml)
│   └── tests/
│
├── opsmate-web/                       # React frontend (separate package)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── Dockerfile
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx                   # React entry point
│   │   ├── App.tsx                    # Root component with providers
│   │   ├── api/
│   │   │   ├── client.ts              # Axios instance with auth interceptors
│   │   │   ├── commands.ts            # Command API endpoints
│   │   │   ├── executions.ts          # Execution API endpoints
│   │   │   └── admin.ts              # Admin API endpoints
│   │   ├── components/
│   │   │   ├── ChatInput.tsx          # Command input with send button
│   │   │   ├── ChatMessage.tsx        # Individual message bubble
│   │   │   ├── ChatThread.tsx         # Scrollable message list
│   │   │   ├── PlanDAG.tsx            # ReactFlow DAG visualization
│   │   │   ├── StepCard.tsx           # Individual step status card
│   │   │   ├── ExecutionHistory.tsx   # Filterable history table
│   │   │   ├── Dashboard.tsx          # Metrics dashboard
│   │   │   ├── ModeIndicator.tsx      # Persistent mode badge
│   │   │   ├── Header.tsx             # App header with nav
│   │   │   └── Sidebar.tsx            # Navigation sidebar
│   │   ├── context/
│   │   │   ├── AuthContext.tsx        # Authentication state
│   │   │   └── ModeContext.tsx        # Execution mode state
│   │   ├── hooks/
│   │   │   ├── useExecution.ts        # Execution lifecycle hook
│   │   │   ├── useWebSocket.ts        # WebSocket connection hook
│   │   │   └── useSSE.ts             # Server-Sent Events hook
│   │   ├── pages/
│   │   │   ├── ChatPage.tsx           # Main chat interface
│   │   │   ├── HistoryPage.tsx        # Execution history
│   │   │   ├── DashboardPage.tsx      # Metrics dashboard
│   │   │   └── AdminPage.tsx         # Admin controls
│   │   ├── types/
│   │   │   └── api.ts                # TypeScript interfaces (mirrors Pydantic models)
│   │   └── utils/
│   │       ├── formatters.ts         # Duration, timestamp formatting
│   │       └── constants.ts          # App constants
│   └── tests/
│
├── docs/                              # Documentation
│   ├── requirements.md                # This document
│   ├── architecture.md               # This document
│   ├── api.md                         # OpenAPI-derived API documentation
│   ├── deployment.md                  # Deployment guide (Docker Compose)
│   ├── development.md                 # Local development setup
│   └── mcp-server-guide.md            # Guide for adding new MCP servers
│
├── scripts/                           # Utility scripts
│   ├── setup.sh                       # One-time development setup
│   ├── seed_demo_data.py             # Seed database with demo executions
│   └── run_tests.sh                  # Test runner with coverage
│
├── tests/                             # Integration and E2E tests
│   ├── conftest.py                    # Shared test fixtures
│   ├── test_api/                      # API endpoint tests
│   ├── test_services/                 # Service layer unit tests
│   ├── test_infra/                    # Infrastructure adapter tests
│   └── test_e2e/                      # End-to-end flow tests
│
├── alembic/                           # Database migrations
│   ├── versions/
│   └── env.py
│
└── monitoring/                        # Observability configuration
    ├── prometheus.yml                 # Prometheus scrape config
    ├── alertmanager.yml               # Alert routing
    ├── alerts.yml                     # Alert rule definitions
    └── grafana-dashboard.json         # Grafana dashboard (optional)
```

### 8.1 Package Dependency Graph

```mermaid
graph TD
    CLI["opsmate-cli"] -->|"HTTP client"| API
    WEB["opsmate-web"] -->|"HTTP/WebSocket"| API

    API["opsmate.api"] --> CORE
    API --> SVCS
    API --> INFRA

    SVCS["opsmate.services"] --> CORE
    SVCS --> INFRA

    INFRA["opsmate.infra"] --> CORE

    CORE["opsmate.core"]

    MCPS["opsmate.mcp_servers.*"] -->|"MCP protocol"| INFRA

    style CORE fill:#e1f5fe
    style SVCS fill:#e1f5fe
    style INFRA fill:#fff3e0
```

**Dependency Rules:**
- `core` has no dependencies on other internal packages (pure models + config)
- `services` depends only on `core` and `infra`
- `infra` depends only on `core`
- `api` depends on `core`, `services`, and `infra`
- `mcp_servers` are independent processes communicating via MCP protocol; they import only `mcp` SDK and external API clients

---

## 9. Deployment Architecture

### 9.1 Docker Compose Stack

```mermaid
graph TB
    subgraph "Docker Compose Network"
        NGINX["nginx<br/>Port 80/443<br/>Static files + proxy"]

        subgraph "Backend Services"
            API["opsmate-api<br/>Port 8000<br/>FastAPI + uvicorn"]
            CLI["opsmate-cli<br/>Interactive shell<br/>--network container:api"]
        end

        subgraph "Data Stores"
            PG[("postgres:16<br/>Port 5432<br/>Execution state + audit")]
            REDIS[("redis:7<br/>Port 6379<br/>Circuit breaker + cache")]
        end

        subgraph "Frontend"
            WEB["opsmate-web<br/>Port 5173 (dev) / 80 (prod)<br/>React + Vite"]
        end

        subgraph "MCP Servers"
            MCP_TAVILY["mcp-tavily<br/>stdio transport"]
            MCP_GITHUB["mcp-github<br/>stdio transport"]
            MCP_SLACK["mcp-slack<br/>stdio transport"]
            MCP_JIRA["mcp-jira<br/>stdio transport"]
            MCP_AWS["mcp-aws-ecs<br/>stdio transport"]
            MCP_PG["mcp-postgres<br/>stdio transport"]
            MCP_CALC["mcp-calculator<br/>stdio transport"]
        end
    end

    NGINX -->|"/api/*"| API
    NGINX -->|"/"| WEB
    NGINX -->|"/ws/*"| API

    API --> PG
    API --> REDIS
    API -->|"stdio spawn"| MCP_TAVILY & MCP_GITHUB & MCP_SLACK & MCP_JIRA & MCP_AWS & MCP_PG & MCP_CALC

    style Backend Services fill:#e1f5fe
    style Data Stores fill:#e8f5e9
    style MCP Servers fill:#fff3e0
```

### 9.2 Environment Configuration

| Environment | Mode | Services |
|---|---|---|
| **Development** | MIXED (Tavily/GitHub/Slack/Jira LIVE; AWS MOCK; PostgreSQL Docker) | Full Docker Compose stack; hot reload for API and Web |
| **Portfolio Demo** | MOCK (all services) | `docker compose up` only; zero credentials |
| **Production** | LIVE (all configured services) | Docker Compose on single VPS; env vars for credentials |

---

## 10. Security Architecture

### 10.1 Threat Model

| Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|
| API key exposure in logs | Medium | High | Redaction middleware; regex-based secret stripping |
| Command injection via LLM | Low | Critical | No `exec`/`eval` of user input; parameterized MCP calls only |
| Unauthorized admin access | Medium | High | Separate admin token; bearer token auth; constant-time comparison |
| MCP server compromise | Low | Medium | Circuit breakers; mock mode default; no sensitive data in mock |
| LLM prompt injection | Medium | Medium | Structured output mode; input validation; no system prompt leakage |
| Data exfiltration via MCP tools | Low | High | Read-only default for database; explicit allowlist for write operations |

### 10.2 Secret Management

```mermaid
graph LR
    ENV["Environment Variables<br/>Host OS"]
    DC["Docker Compose<br/>env_file: .env"]
    PYD["Pydantic-Settings<br/>Validation"]
    APP["FastAPI App<br/>Read-only Settings"]
    MCP["MCP Server Processes<br/>Inherited env"]
    API_EXT["External APIs"]

    ENV -->|"Loaded at startup"| DC
    DC --> PYD
    PYD -->|"Validated + typed"| APP
    APP -->|"Per-server env dict"| MCP
    MCP -->|"HTTP requests"| API_EXT

    REDACT["Redaction Middleware"] -->|"Strip secrets"| LOGS[("Logs / Audit")]
    APP --> REDACT

    style ENV fill:#ffebee
    style REDACT fill:#ffebee
```

---

## 11. Performance Budget

| Operation | Target (MOCK) | Target (LIVE) | Measurement |
|---|---|---|---|
| Intent classification | < 1s | < 1s | LLM API call + regex |
| Plan generation (template) | < 500ms | < 500ms | Template match + validation |
| Plan generation (zero-shot) | < 3s | < 3s | LLM call + validation |
| Single tool execution | < 500ms | < 3s | MCP call + persistence |
| 4-step DAG execution | < 5s | < 20s | Parallel where possible |
| Full E2E (single-tool) | < 2s | < 5s | Command → rendered output |
| Full E2E (multi-step) | < 10s | < 30s | Command → rendered output |
| State persistence (per step) | < 50ms | < 50ms | PostgreSQL write |
| Web UI time-to-interactive | < 3s | < 3s | Lighthouse metric |
| CLI startup | < 1s | < 1s | `opsmate --help` |

---

## 12. Testing Strategy

| Layer | Framework | Coverage Target | Key Tests |
|---|---|---|---|
| **Unit** | pytest + pytest-asyncio | 80% | Service logic, state transitions, error classification, mock data generation |
| **Integration** | pytest + TestClient | 70% | API endpoints, database operations, MCP hub connectivity |
| **E2E** | pytest + playwright (CLI via pexpect) | 60% | Full command → output flows for all 5 plan templates |
| **Contract** | Pydantic schema validation | 100% | Mock response schema == Live response schema for all tools |
| **Load** | locust | Baseline | 50 concurrent users, 100 requests/minute |

---

## 13. Revision History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2025-06-01 | Jashwanth Nag Veepuri | Initial architecture specification. |

---

*End of Architecture Specification*
