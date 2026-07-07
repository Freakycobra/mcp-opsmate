# mcp-opsmate — Infrastructure Automation MCP Terminal

## Requirements Specification

**Version:** 1.0  
**Author:** Jashwanth Nag Veepuri  
**Date:** 2025-06-01  
**Status:** Draft  

---

## 1. Project Overview

**mcp-opsmate** is an AI-powered infrastructure automation terminal that enables platform engineers and SREs to execute complex operational workflows through natural language commands. Built on the Model Context Protocol (MCP) — Anthropic's open standard for AI-tool connectivity — OpsMate breaks user commands into multi-step execution plans, dynamically discovers and chains MCP tool calls across diverse infrastructure backends, and produces actionable, structured output suitable for production incident response and daily operational tasks.

The system targets the gap between raw LLM chat interfaces and production-grade automation platforms. Unlike generic chatbots, OpsMate is purpose-built for infrastructure operations: it understands operational semantics (health checks, metric thresholds, incident workflows), respects execution ordering constraints (DAG-based step planning), persists execution state for long-running workflows, and provides first-class observability through structured audit trails. It operates in MOCK mode by default for zero-friction onboarding, with seamless graduation to LIVE mode for production use — a critical requirement for enterprise adoption where sandbox experimentation precedes production deployment.

OpsMate serves as both a CLI tool (Rich TUI for terminal-native workflows) and a web application (React UI for demonstrations and non-technical stakeholders). The architecture is designed for extensibility: new MCP servers (internal APIs, cloud providers, observability platforms) can be onboarded with minimal configuration, and the intent planner automatically incorporates newly available tools into its planning scope without code changes. This document specifies the functional and non-functional requirements, user stories, and explicit scope boundaries for the v1.0 release.

---

## 2. Functional Requirements

### 2.1 Command Processing & Intent Classification

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-01** | The system SHALL accept natural language commands from both CLI and Web UI input interfaces. | P0 | Commands up to 2000 characters are accepted; both interfaces produce identical parsed representations. |
| **FR-02** | The system SHALL classify user intent into one or more operational categories: `QUERY`, `ACTION`, `ANALYZE`, `NOTIFY`, `CORRELATE`, `REMEDIATE`. | P0 | Classification accuracy >= 90% on test suite of 50 representative infrastructure commands; multi-label classification supported for compound commands. |
| **FR-03** | The system SHALL extract structured parameters from commands: service names, time ranges, thresholds, resource identifiers, severity levels, and notification targets. | P0 | Parameter extraction covers at minimum: service names (regex + LLM), relative time ranges ("last 2h" → datetime tuple), numeric thresholds, AWS resource ARNs/patterns, Jira ticket IDs, Slack channel names. |
| **FR-04** | The system SHALL perform entity resolution to map ambiguous identifiers (e.g., "payment-service") to canonical resource names using a configurable lookup dictionary. | P1 | Lookup dictionary supports fuzzy matching (Levenshtein distance <= 2); unresolved entities trigger clarification prompt rather than silent failure. |
| **FR-05** | The system SHALL reject out-of-scope commands with a clear explanation and suggested rephrasing. | P1 | Rejection response includes: reason for rejection, examples of supported commands, and confidence score of rejection decision. |

### 2.2 Execution Plan Generation

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-06** | The system SHALL generate an execution plan as a directed acyclic graph (DAG) of steps, where edges represent data dependencies between steps. | P0 | Plan contains: ordered list of steps, dependency graph (parent → child), expected input/output schemas per step, estimated execution time, and confidence score. |
| **FR-07** | The system SHALL support plan templates for common operational patterns: health-check-and-remediate, incident-response, deployment-validation, cost-analysis, compliance-audit. | P1 | At least 5 plan templates defined; templates reduce planning latency by >= 40% vs. zero-shot planning. |
| **FR-08** | The system SHALL validate the execution plan against available MCP tools before execution — verifying that each required tool is connected and the requested operation is supported. | P0 | Validation produces a readiness report: available tools, missing tools, fallback options; plan execution blocked if critical tools unavailable (unless user overrides). |
| **FR-09** | The system SHALL present the execution plan to the user for confirmation before execution, with an option to skip confirmation via `--auto-approve` flag or UI toggle. | P0 | Plan display includes: step descriptions, tools involved, estimated cost (if applicable), and risk level (LOW/MEDIUM/HIGH based on write operations). |
| **FR-10** | The system SHALL support plan editing: users can remove steps, reorder independent steps, or modify step parameters before execution. | P2 | Web UI supports drag-and-drop plan editing; CLI supports step selection via interactive checklist. |

### 2.3 MCP Tool Discovery & Execution

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-11** | The system SHALL dynamically discover available tools from all connected MCP servers at startup, caching tool schemas for performance. | P0 | Tool discovery completes within 5 seconds for 7 MCP servers; cache invalidated and reloaded on MCP server reconnection or explicit refresh command. |
| **FR-12** | The system SHALL route each execution step to the appropriate MCP server based on tool name matching, with explicit server-to-tool mapping defined in configuration. | P0 | Tool routing supports: exact name match, server-prefixed disambiguation (`aws-ecs/describe_pods`), and fallback server selection for replicated tools. |
| **FR-13** | The system SHALL execute MCP tool calls asynchronously, respecting dependency ordering defined in the DAG. Independent steps execute in parallel; dependent steps execute sequentially. | P0 | Parallel execution achieves >= 60% concurrency for plans with 4+ independent steps; execution order violations are impossible by construction. |
| **FR-14** | The system SHALL pass outputs from parent steps as inputs to child steps through a typed context object, with schema validation at each handoff. | P0 | Context object is immutable per-step (copy-on-write); schema mismatches produce clear error messages with actual vs. expected type information. |
| **FR-15** | The system SHALL support conditional step execution based on the results of previous steps (e.g., "only restart if CPU > 80%"). | P1 | Conditional expressions use Jinja2-like syntax with access to step outputs; conditions evaluated server-side before step dispatch. |

### 2.4 Error Handling & Recovery

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-16** | The system SHALL implement retry logic with exponential backoff (base=1s, factor=2, max=3 attempts) for transient MCP tool failures (timeout, rate limit, connection reset). | P0 | Retry behavior is configurable per-MCP-server; rate limit responses (HTTP 429) respect `Retry-After` header when present. |
| **FR-17** | The system SHALL implement a circuit breaker pattern for MCP servers: after 5 consecutive failures, the server enters OPEN state and subsequent calls fail fast; half-open probe attempted after 30s. | P0 | Circuit breaker state transitions logged; half-open probe uses a lightweight health-check tool call; manual reset supported via admin API. |
| **FR-18** | The system SHALL support partial failure recovery: if a non-critical step fails, the plan continues with degraded functionality, clearly marking the affected output as incomplete. | P1 | Steps marked as `critical: true` in the plan cause full execution halt on failure; non-critical steps log warning and continue; final output indicates which data is missing and why. |
| **FR-19** | The system SHALL escalate to human-in-the-loop for critical failures: destructive operations (restart, delete) that fail, or any failure when confidence < 70%, require explicit user approval to continue or abort. | P0 | Escalation prompt includes: failure details, proposed remediation options, and timeout (default: 5 minutes before auto-abort). |
| **FR-20** | The system SHALL provide detailed error context for every failure: error classification (TRANSIENT/PERMANENT/CONFIGURATION), root cause summary, and suggested remediation actions. | P1 | Error context includes: MCP server name, tool name, input parameters (sanitized), stack trace (in DEBUG mode), and documentation links where applicable. |

### 2.5 Execution State & Persistence

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-21** | The system SHALL persist execution state to PostgreSQL after every step completion, enabling pause/resume of long-running workflows. | P0 | State persistence latency < 50ms; state includes: plan DAG, current step, step results, context object, and timestamps. |
| **FR-22** | The system SHALL support graceful shutdown: on SIGTERM, in-flight steps complete, state is persisted, and execution resumes on restart. | P0 | SIGTERM handling completes within 30s (configurable timeout); resumption restores exact execution context including partial step results. |
| **FR-23** | The system SHALL expose a `/executions` API for querying execution history: list, filter by status/date/range, and retrieve detailed execution logs. | P0 | API supports pagination (default 20/page), status filtering (pending/planning/executing/completed/failed/paused), and date range queries. |
| **FR-24** | The system SHALL automatically clean up execution history older than 30 days (configurable), archiving completed executions to compressed JSON before deletion. | P2 | Archive stored in configurable location (local filesystem or S3); cleanup runs daily at 02:00 UTC. |

### 2.6 Audit Trail & Observability

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-25** | The system SHALL generate structured JSON audit logs for every operation: command received, plan generated, step started/completed/failed, tool call details, and final output. | P0 | Audit log schema is versioned; includes: timestamp (UTC, RFC3339), execution_id, user_id (if available), action type, and duration_ms. |
| **FR-26** | The system SHALL redact all secrets (API keys, tokens, passwords) from logs and audit trails, replacing them with `[REDACTED:<key-type>]`. | P0 | Redaction covers: environment variable names matching `*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`; regex-based redaction for connection strings. |
| **FR-27** | The system SHALL expose a `/health` endpoint returning service health, MCP server connection status, and basic metrics (uptime, request count, error rate). | P0 | Health check completes within 2s; returns HTTP 200 if all critical MCP servers connected, HTTP 503 if any critical server down > 60s. |
| **FR-28** | The system SHALL emit OpenTelemetry-compatible traces for execution lifecycles, with spans for planning, tool execution, and state persistence. | P2 | Traces exportable to Jaeger/Zipkin; each span includes MCP server name, tool name, and execution duration. |

### 2.7 Execution Mode Management

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-29** | The system SHALL support three execution modes: MOCK (synthetic data), LIVE (real API calls), and MIXED (per-service configuration). | P0 | Mode determined by: `EXECUTION_MODE` env var (global default) + per-MCP-server `mode` override in config; MIXED mode resolves per-tool at execution time. |
| **FR-30** | In MOCK mode, the system SHALL return realistic synthetic data generated by deterministic seeded faker logic, with configurable latency injection (50-200ms per call). | P0 | Synthetic data matches real API response schemas (validated via Pydantic models); same seed produces identical outputs for reproducible testing. |
| **FR-31** | In LIVE mode, the system SHALL make real API calls using credentials from environment variables only; credentials SHALL never be logged, stored in state, or returned in responses. | P0 | Credential loading uses `pydantic-settings` with `env_prefix`; missing credentials produce clear error at startup (not runtime); credential rotation requires only env var update + service restart. |
| **FR-32** | Mode switching SHALL be possible at runtime via the `/admin/mode` API endpoint (protected by admin token), with in-flight executions continuing in their original mode. | P1 | Mode change applies only to new executions; existing executions unaffected; change logged with admin identity and timestamp. |
| **FR-33** | The system SHALL clearly indicate the execution mode of every response: mode badge in CLI output, mode indicator in Web UI, and `execution_mode` field in all API responses. | P0 | Mode indication is visually distinct (MOCK = amber warning, LIVE = green indicator, MIXED = split indicator); cannot be disabled. |

### 2.8 CLI Interface (Rich TUI)

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-34** | The CLI SHALL use the Rich library for terminal output: syntax-highlighted JSON for tool results, colored tables for status reports, progress spinners during execution, and panel-based layout for plan display. | P0 | CLI runs in any terminal supporting 256 colors; falls back to plain text for dumb terminals (`TERM=dumb`); supports terminal widths 80-300 characters. |
| **FR-35** | The CLI SHALL support interactive command input with history (up-arrow recall) and tab-completion for known service names and command patterns. | P1 | History persisted to `~/.opsmate/history`; completion suggestions include: service names from entity dictionary, common time range patterns, and severity levels. |
| **FR-36** | The CLI SHALL support streaming output: plan generation and step execution results appear in real-time as they are produced, not batched at completion. | P0 | Streaming latency < 500ms from server event to terminal display; supports plan confirmation prompt mid-stream. |
| **FR-37** | The CLI SHALL support command-line flags: `--mode`, `--auto-approve`, `--output json`, `--verbose`, `--execution-id <id>` (for resuming), and `--config <path>`. | P1 | All flags documented in `--help`; flag values validated before server connection; invalid flags produce actionable error messages. |

### 2.9 Web UI (React)

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-38** | The Web UI SHALL provide a chat-style interface for command input, with message history displayed as a scrollable conversation thread. | P0 | Interface resembles modern chat UIs (ChatGPT/Claude); supports markdown rendering in responses; code blocks have copy-to-clipboard buttons. |
| **FR-39** | The Web UI SHALL render execution plans as interactive DAG visualizations (using ReactFlow or equivalent), showing step status, dependencies, and real-time progress. | P0 | DAG updates in real-time via WebSocket; completed steps green, in-progress blue, failed red, pending gray; clickable nodes show step details. |
| **FR-40** | The Web UI SHALL include an "Execution History" page with filtering, search, and detail view for past executions. | P1 | History page shows: execution ID, command, status, duration, mode, and timestamp; detail view shows full plan DAG and step outputs. |
| **FR-41** | The Web UI SHALL display a persistent execution mode indicator in the header, and require explicit user acknowledgment when switching from MOCK to LIVE mode. | P0 | Mode switch triggers confirmation dialog explaining implications; LIVE mode indicator pulses to draw attention; MIXED mode shows per-service breakdown. |

### 2.10 Administrative & Configuration

| ID | Requirement | Priority | Acceptance Criteria |
|---|---|---|---|
| **FR-42** | The system SHALL load configuration from a hierarchical source: default values → `config.yaml` file → environment variables → CLI flags (later overrides earlier). | P0 | Configuration schema validated with Pydantic at startup; invalid config produces startup failure with detailed validation errors; config reloadable via SIGHUP. |
| **FR-43** | The system SHALL support MCP server configuration via `mcp_servers` section in config: server name, transport type (stdio/sse), command/URL, environment variables, timeout, and execution mode override. | P0 | Configuration supports both stdio (subprocess-based) and SSE (HTTP-based) MCP transports; timeout configurable per-server (default 30s). |
| **FR-44** | The system SHALL provide an admin API (`/admin/*`) protected by bearer token authentication for: mode switching, MCP server health, execution querying, and configuration inspection. | P1 | Admin endpoints return 401 for missing/invalid token; token validated via constant-time comparison; admin token loaded from `ADMIN_API_TOKEN` env var. |

---

## 3. Non-Functional Requirements

### 3.1 Performance

| ID | Requirement | Target | Measurement Method |
|---|---|---|---|
| **NFR-01** | Single-tool command end-to-end latency (command received to response rendered) shall not exceed **2 seconds** in MOCK mode. | < 2s p95 | Load testing with 100 sequential single-tool commands; measure wall-clock time. |
| **NFR-02** | Multi-step chain (4+ steps) end-to-end latency shall not exceed **30 seconds** in MOCK mode with parallel execution. | < 30s p95 | Load testing with 20 multi-step commands; measure wall-clock time including planning. |
| **NFR-03** | Concurrent execution of up to **10 independent execution plans** shall not degrade single-plan latency by more than 25%. | < 25% degradation | Parallel load testing: 1 plan baseline vs. 10 plans concurrent; compare p95 latencies. |
| **NFR-04** | LLM planning latency shall not exceed **5 seconds** for commands up to 500 characters. | < 5s p95 | Instrumented measurement of planning phase duration across 50 test commands. |
| **NFR-05** | Web UI time-to-interactive shall not exceed **3 seconds** on a 100Mbps connection. | < 3s | Lighthouse performance audit; measured from navigation to first user input acceptance. |

### 3.2 Reliability

| ID | Requirement | Target | Measurement Method |
|---|---|---|---|
| **NFR-06** | Service uptime target of **99.9%** (excluding planned maintenance windows). | 99.9% | Monitored via `/health` endpoint polling; downtime defined as 3 consecutive health check failures. |
| **NFR-07** | The system SHALL degrade gracefully when individual MCP servers are unavailable: continue operating with remaining servers, marking affected capabilities as unavailable. | 100% availability with N-1 MCP servers | Kill individual MCP server processes during execution; verify system continues with clear degradation indicators. |
| **NFR-08** | Zero data loss for execution state: all executions recoverable to their last completed step after unexpected process termination. | 0 data loss | SIGKILL simulation during 50 executions; verify all recoverable to last completed step on restart. |
| **NFR-09** | No memory leaks: continuous operation for 7 days shall not increase memory usage by more than 10% from baseline. | < 10% growth | 7-day soak test with periodic execution submissions; monitor RSS via `/metrics` endpoint. |

### 3.3 Security

| ID | Requirement | Target | Measurement Method |
|---|---|---|---|
| **NFR-10** | API keys and secrets SHALL exist only in environment variables; no secrets SHALL be committed to source control, logged, or returned in API responses. | 0 secret leakage | Automated scanning (git-secrets, truffleHog) on CI; manual code review of all credential handling. |
| **NFR-11** | All API endpoints (except `/health`) SHALL require authentication via configurable mechanism: API key header, JWT bearer token, or mTLS. | 100% coverage | Automated endpoint enumeration test; verify 401 response for unauthenticated requests to all non-health endpoints. |
| **NFR-12** | Admin endpoints SHALL be protected by a separate, stronger authentication mechanism than regular API endpoints. | Separate auth layer | Admin token must be distinct from regular API key; admin endpoints reject regular API key with 403. |
| **NFR-13** | Input commands SHALL be sanitized to prevent injection attacks: no shell command execution, no eval of user input, parameterized MCP tool calls only. | 0 injection surface | Static analysis (Bandit, Semgrep) for exec/eval patterns; architectural review confirms no code path from user input to system execution. |

### 3.4 Extensibility

| ID | Requirement | Target | Measurement Method |
|---|---|---|---|
| **NFR-14** | Onboarding a new MCP server SHALL require **fewer than 50 lines** of configuration/code changes. | < 50 lines | Time-bounded exercise: onboard a new mock MCP server; count lines changed in non-test code. |
| **NFR-15** | The system SHALL use a plugin-style architecture where MCP servers are discovered and loaded dynamically at runtime based on configuration, without code changes to the core orchestrator. | Dynamic discovery | Add new MCP server to config and restart; verify tool discovery and routing work without code changes. |
| **NFR-16** | Adding a new plan template SHALL require only a YAML/JSON template file — no code changes. | 0 code changes | Template-driven plan generation; templates validated against schema at load time. |

### 3.5 Observability

| ID | Requirement | Target | Measurement Method |
|---|---|---|---|
| **NFR-17** | All log output SHALL be structured JSON (when `LOG_FORMAT=json`) or human-readable with consistent formatting (when `LOG_FORMAT=text`). | 100% coverage | Log output inspection; automated linting of log statements for non-JSON output in JSON mode. |
| **NFR-18** | Every execution SHALL generate a traceable execution chain: execution ID propagated through all components and log entries. | 100% coverage | Correlation ID (`X-Execution-ID` header) present in all log entries for a given execution; grep-able across services. |
| **NFR-19** | The system SHALL expose Prometheus-compatible metrics at `/metrics`: request count, latency histograms, error rates, MCP server connection status, and active execution count. | Full coverage | `/metrics` endpoint scrape test; verify all documented metrics present and correctly labeled. |
| **NFR-20** | Alerting rules SHALL be definable for key health indicators: MCP server disconnection > 60s, error rate > 5% over 5min, memory usage > 85%. | 3 alert rules | Alertmanager-compatible rule definitions in `alerts.yml`; validated with promtool. |

### 3.6 Compatibility & Deployment

| ID | Requirement | Target | Measurement Method |
|---|---|---|---|
| **NFR-21** | The system SHALL run on Python 3.13+ and be deployable via Docker Compose for local development and single-node production. | Python 3.13 | CI matrix testing on Python 3.13; Docker Compose smoke test on clean VM. |
| **NFR-22** | The CLI SHALL be installable via `pip install opsmate-cli` and support macOS (arm64/x86_64) and Linux (x86_64/arm64). | 4 platforms | Wheel building in CI for all target platforms; installation test on each. |
| **NFR-23** | All MCP server mock implementations SHALL have response schemas identical to their LIVE counterparts, validated by shared Pydantic models. | Schema parity | Automated schema diff test: compare mock response schema to live response schema for all 7 MCP servers. |

---

## 4. User Stories

### US-1: On-Call Engineer — Health Check and Remediation

> **As an** on-call SRE responsible for payment processing microservices,  
> **I want to** type "Check if payment-service pods are healthy in EKS, show CPU trends for the last 2 hours, restart any pod above 80% CPU, and alert the on-call Slack channel",  
> **So that** I can identify and remediate performance degradation without manually running 4 separate kubectl + aws + slack commands at 3 AM.

**Acceptance Criteria:**
- System generates a 4-step DAG: describe_pods → get_cloudwatch_metrics → conditional_restart_pods → send_slack_message
- Plan presented for confirmation before execution
- CPU threshold (80%) extracted from command and passed to conditional step
- Slack channel "on-call" resolved from configuration
- Full execution completes within 20 seconds in MOCK mode
- Final output: table of pod health, CPU trend graph (text-based), restart summary, Slack delivery confirmation

### US-2: Incident Commander — Ticket and CI Correlation

> **As an** incident commander during a Sev-1 outage,  
> **I want to** type "Show all P1 tickets assigned to the on-call engineer, cross-reference with CI pipeline failures in the last 24 hours, and draft a status update",  
> **So that** I can correlate incident tickets with deployment failures and communicate status to stakeholders rapidly.

**Acceptance Criteria:**
- System queries Jira for P1 tickets assigned to on-call
- System queries GitHub Actions for failed workflows in last 24h
- Correlation performed on service name / repository matching
- Draft status update generated combining ticket summaries and CI failure context
- Output includes: ticket table, CI failure table, correlation matrix, drafted Slack message with edit option

### US-3: Platform Engineer — Performance Regression Analysis

> **As a** platform engineer responsible for Lambda optimization,  
> **I want to** type "Compare current Lambda cold-start latency against last week, identify the 5 worst-performing functions, and show cost impact",  
> **So that** I can prioritize optimization efforts with data-backed recommendations.

**Acceptance Criteria:**
- System queries CloudWatch for Lambda duration metrics (current week vs. previous week)
- Calculator MCP server computes percentage changes and cost deltas
- Top 5 worst-performing functions ranked by p99 cold-start latency increase
- Cost impact calculated from invocation count × duration × Lambda pricing
- Output: comparison table, ranked worst-performers, cost projection, recommended actions

### US-4: New Team Member — Zero-Config Onboarding

> **As a** new engineer joining the platform team,  
> **I want to** clone the repository, run `docker compose up`, and immediately execute sample commands without configuring API keys,  
> **So that** I can learn the tool's capabilities through hands-on experimentation in a safe sandbox environment.

**Acceptance Criteria:**
- `docker compose up` starts all services (FastAPI backend, PostgreSQL, React frontend, all MCP servers)
- Default MOCK mode requires zero external credentials
- Built-in demo commands available via `/examples` endpoint
- First command execution succeeds within 2 minutes of `docker compose up`
- Clear documentation guides transition from MOCK to LIVE mode

### US-5: Engineering Manager — Operational Visibility

> **As an** engineering manager responsible for platform reliability,  
> **I want to** view a dashboard of recent automated operations: commands executed, success rates, average execution time, and which MCP servers are most frequently used,  
> **So that** I can understand team operational patterns and identify areas for automation investment.

**Acceptance Criteria:**
- Web UI includes a dashboard page with summary statistics
- Metrics: total executions (24h/7d/30d), success rate, average duration, top commands, MCP server usage
- Execution history filterable by date range, status, and user
- Data exportable to CSV/JSON for further analysis
- Dashboard auto-refreshes every 60 seconds

### US-6: Security Auditor — Compliance Verification

> **As a** security auditor reviewing operational tooling,  
> **I want to** verify that no secrets are logged, all operations are auditable, and the system can operate in read-only mode for sensitive environments,  
> **So that** I can approve the tool for use in regulated production environments.

**Acceptance Criteria:**
- Audit logs contain: who (user ID), what (command + plan), when (timestamp), result (success/failure)
- Zero secrets in logs (verified by automated scanning)
- Read-only mode: all write operations (restart, create, delete) blocked at the orchestrator level
- Execution logs retained for configurable retention period (default 30 days)
- Admin actions (mode switches, config changes) logged separately with elevated detail

---

## 5. Out of Scope (Explicitly Not Building)

The following capabilities are explicitly excluded from the v1.0 release. They are recognized as valuable but deferred to future iterations to maintain scope discipline and deliver a focused, high-quality core product.

| # | Out-of-Scope Item | Rationale | Future Consideration |
|---|---|---|---|
| **OS-01** | **Multi-user authentication and RBAC** | v1.0 targets single-user/single-team deployment; authentication via shared API key only. | v2.0: OAuth2/OIDC integration with role-based access control per MCP server. |
| **OS-02** | **Multi-region / distributed deployment** | Single-node Docker Compose deployment satisfies portfolio demonstration and small-team use cases. | v2.0: Kubernetes Helm chart, state externalization to Redis/PostgreSQL for horizontal scaling. |
| **OS-03** | **Custom MCP server authoring framework** | Users can add existing MCP servers via config; creating new MCP servers requires separate development. | v2.0: SDK templates and scaffolding for internal MCP server development. |
| **OS-04** | **Workflow scheduling and cron triggers** | v1.0 is on-demand command execution only; no scheduled or event-triggered workflows. | v2.0: APScheduler integration for recurring operational checks. |
| **OS-05** | **AI-powered anomaly detection** | Metric analysis uses threshold-based rules; no ML-based anomaly detection. | v2.0: Integration with existing observability platforms (Datadog, Grafana) for anomaly signals. |
| **OS-06** | **Multi-LLM support** | v1.0 uses OpenAI GPT-4o exclusively; abstraction exists but only one provider implemented. | v2.0: Anthropic Claude, local models (Ollama), and Azure OpenAI support. |
| **OS-07** | **Voice input / output** | Text-only interface for v1.0; voice considered out of scope for infrastructure tooling. | Future: Unlikely priority; infrastructure engineers prefer text interfaces. |
| **OS-08** | **Mobile application** | Web UI is desktop-optimized; mobile responsive design is sufficient for v1.0. | Future: Progressive Web App (PWA) capabilities if demand exists. |
| **OS-09** | **Real-time collaborative editing** | Single-user command execution; no shared sessions or collaborative plan editing. | Future: WebSocket-based shared sessions for pair troubleshooting. |
| **OS-10** | **Automated remediation without human approval** | All destructive operations require explicit confirmation; no fully autonomous remediation loops. | v2.0: Configurable auto-approval for specific low-risk remediation patterns with audit trail. |
| **OS-11** | **Cost optimization and billing integration** | Cost calculations use static pricing tables; no integration with cloud billing APIs. | v2.0: AWS Cost Explorer / GCP Billing API integration for accurate cost analysis. |
| **OS-12** | **Configuration drift detection** | No infrastructure-as-state comparison; commands operate on current state only. | Future: Integration with Terraform state or CloudFormation drift detection. |

---

## 6. Glossary

| Term | Definition |
|---|---|
| **MCP** | Model Context Protocol — Anthropic's open standard for connecting LLMs to external tools and data sources. |
| **MCP Server** | A process that exposes tools, resources, and prompts via the MCP protocol; OpsMate connects to 7 MCP servers. |
| **DAG** | Directed Acyclic Graph — a graph data structure with directed edges and no cycles; used to represent execution plans where steps have dependencies. |
| **MOCK Mode** | Execution mode where all MCP tool calls return synthetic data; requires no external credentials. |
| **LIVE Mode** | Execution mode where MCP tool calls make real API requests to external services. |
| **MIXED Mode** | Execution mode where some MCP servers operate in LIVE mode and others in MOCK mode, configured per-server. |
| **Intent Planner** | The component responsible for breaking a natural language command into a structured execution plan (DAG). |
| **Step Executor** | The component responsible for executing individual steps in the execution plan by calling MCP tools. |
| **State Manager** | The component responsible for persisting and restoring execution state to enable pause/resume. |
| **Circuit Breaker** | A design pattern that prevents cascading failures by temporarily rejecting requests to a failing service. |

---

## 7. Revision History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2025-06-01 | Jashwanth Nag Veepuri | Initial requirements specification. |

---

*End of Requirements Specification*
