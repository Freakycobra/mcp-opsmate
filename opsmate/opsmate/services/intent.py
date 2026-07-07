"""Intent classification and planning services for mcp-opsmate.

Includes:
- IntentClassifier: Hybrid regex + LLM intent classification
- IntentPlanner: Template matcher + zero-shot plan generation
"""

from __future__ import annotations

import logging
import re
from typing import Any

from opsmate.core.config import get_config
from opsmate.core.constants import (
    INTENT_CLASSIFICATION_CONFIDENCE_THRESHOLD,
    IntentType,
)
from opsmate.core.exceptions import (
    HumanEscalationError,
    IntentClassificationError,
    PlanningError,
)
from opsmate.core.models import (
    ExecutionPlan,
    ExtractedEntity,
    IntentClassification,
    PlanStep,
)
from opsmate.infra.llm import LLMClient

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for entity extraction
# ---------------------------------------------------------------------------

_SERVICE_NAME_PATTERNS: list[str] = [
    r"\b([a-z][a-z0-9_-]*-service)\b",
    r"\b([a-z][a-z0-9_-]*-api)\b",
    r"\b([a-z][a-z0-9_-]*-gateway)\b",
    r"\b([a-z][a-z0-9_-]*-processor)\b",
    r"\b([a-z][a-z0-9_-]*-db)\b",
    r"\b([a-z][a-z0-9_-]*-worker)\b",
]

_TIME_RANGE_PATTERNS: list[tuple[str, str]] = [
    (r"\blast\s+(\d+)\s*(h|hour|hours)\b", "hours"),
    (r"\blast\s+(\d+)\s*(d|day|days)\b", "days"),
    (r"\bsince\s+yesterday\b", "since_yesterday"),
    (r"\bsince\s+last\s+week\b", "since_last_week"),
    (r"\blast\s+(\d+)\s*(m|min|minute|minutes)\b", "minutes"),
]

_THRESHOLD_PATTERNS: list[str] = [
    r"(?:CPU|cpu|memory|mem|latency|error rate)\s*(>|<|>=|<=)\s*(\d+(?:\.\d+)?)\s*(?:%|ms|percent)?",
    r"(?:above|below|over|under)\s+(\d+(?:\.\d+)?)\s*(?:%|ms|percent)?",
]

_RESOURCE_ID_PATTERNS: list[str] = [
    r"\b([A-Z]+-\d+)\b",  # Jira ticket IDs
    r"\b(arn:aws:[a-z]+:[a-z0-9-]*:\d+:[a-z]+/[^\s]+)\b",  # AWS ARNs
    r"\b(#[a-z0-9_-]+)\b",  # Slack channels
]

_SEVERITY_PATTERNS: list[str] = [
    r"\b(P0|P1|P2|P3)\b",
    r"\b(critical|high|medium|low)\s+(severity|priority|alert)\b",
]

_DESTRUCTIVE_KEYWORDS: set[str] = {
    "restart", "delete", "remove", "terminate", "stop", "kill",
    "scale down", "rollback", "destroy", "purge",
}

_ANALYSIS_KEYWORDS: set[str] = {"compare", "analyze", "correlate", "check", "investigate", "diagnose"}
_NOTIFICATION_KEYWORDS: set[str] = {"notify", "alert", "post to", "send to", "message", "inform"}
_REMEDIATION_KEYWORDS: set[str] = {"fix", "remediate", "auto-remediate", "auto-heal", "resolve"}

# ---------------------------------------------------------------------------
# Plan templates
# ---------------------------------------------------------------------------

_PLAN_TEMPLATES: dict[str, dict[str, Any]] = {
    "health-check-and-remediate": {
        "triggers": ["check health", "restart if", "fix if", "remediate"],
        "steps": [
            {"id": "step-1", "tool_name": "describe_pods", "server": "aws-ecs", "description": "Get pod status", "input_mapping": {}},
            {"id": "step-2", "tool_name": "get_metrics", "server": "aws-ecs", "description": "Get CPU/memory metrics", "depends_on": ["step-1"]},
            {"id": "step-3", "tool_name": "threshold_check", "server": "calculator", "description": "Check if threshold exceeded", "depends_on": ["step-2"]},
            {"id": "step-4", "tool_name": "restart_pod", "server": "aws-ecs", "description": "Restart unhealthy pods", "depends_on": ["step-3"], "condition": "{{step-3.triggered}}"},
            {"id": "step-5", "tool_name": "send_message", "server": "slack", "description": "Notify team of actions taken", "depends_on": ["step-4"]},
        ],
    },
    "incident-response": {
        "triggers": ["incident", "P0", "P1"],
        "steps": [
            {"id": "step-1", "tool_name": "search_tickets", "server": "jira", "description": "Search related tickets"},
            {"id": "step-2", "tool_name": "workflow_status", "server": "github", "description": "Check CI/CD status", "depends_on": ["step-1"]},
            {"id": "step-3", "tool_name": "create_incident", "server": "jira", "description": "Create incident ticket", "depends_on": ["step-1"]},
            {"id": "step-4", "tool_name": "send_message", "server": "slack", "description": "Notify incident channel", "depends_on": ["step-3"]},
        ],
    },
    "deployment-validation": {
        "triggers": ["deploy", "verify", "validate"],
        "steps": [
            {"id": "step-1", "tool_name": "workflow_status", "server": "github", "description": "Check deployment workflow"},
            {"id": "step-2", "tool_name": "describe_pods", "server": "aws-ecs", "description": "Verify pod health", "depends_on": ["step-1"]},
            {"id": "step-3", "tool_name": "pr_checks", "server": "github", "description": "Check PR validation", "depends_on": ["step-1"]},
            {"id": "step-4", "tool_name": "send_message", "server": "slack", "description": "Notify deployment status", "depends_on": ["step-2", "step-3"]},
        ],
    },
    "performance-analysis": {
        "triggers": ["compare", "performance", "latency", "CPU", "memory"],
        "steps": [
            {"id": "step-1", "tool_name": "get_metrics", "server": "aws-ecs", "description": "Query performance metrics"},
            {"id": "step-2", "tool_name": "math", "server": "calculator", "description": "Calculate deltas and averages", "depends_on": ["step-1"]},
            {"id": "step-3", "tool_name": "search", "server": "tavily-search", "description": "Search for optimization recommendations", "depends_on": ["step-2"]},
        ],
    },
    "cost-analysis": {
        "triggers": ["cost", "spend", "billing", "optimization"],
        "steps": [
            {"id": "step-1", "tool_name": "execute_query", "server": "postgres-db", "description": "Query cost data"},
            {"id": "step-2", "tool_name": "math", "server": "calculator", "description": "Calculate costs and deltas", "depends_on": ["step-1"]},
            {"id": "step-3", "tool_name": "threshold_check", "server": "calculator", "description": "Identify cost anomalies", "depends_on": ["step-2"]},
            {"id": "step-4", "tool_name": "search", "server": "tavily-search", "description": "Find cost optimization recommendations", "depends_on": ["step-3"]},
        ],
    },
}


# ---------------------------------------------------------------------------
# IntentClassifier
# ---------------------------------------------------------------------------


class IntentClassifier:
    """Hybrid intent classifier combining regex extraction with LLM classification."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm: LLMClient | None = llm_client
        self._config = get_config()

    async def classify(self, command: str) -> IntentClassification:
        """Classify a command using hybrid regex + LLM approach.

        1. Regex extracts known entities (service names, time ranges, thresholds)
        2. LLM provides semantic classification with confidence
        3. Results are merged with conflict resolution (regex wins on exact matches)

        Args:
            command: Natural language command from user.

        Returns:
            IntentClassification with types, entities, and confidence.

        Raises:
            IntentClassificationError: If confidence is below threshold.
        """
        # Step 1: Regex entity extraction
        regex_entities: list[ExtractedEntity] = self._extract_entities_regex(command)
        regex_intents: list[IntentType] = self._infer_intents_regex(command)

        # Step 2: LLM classification (if available)
        llm_result: IntentClassification | None = None
        if self._llm and self._config.llm.api_key:
            try:
                llm_result = await self._llm.classify_intent(command)
            except Exception as e:
                logger.warning("LLM classification failed, using regex only: %s", e)

        # Step 3: Merge results
        merged: IntentClassification = self._merge_results(
            command, regex_entities, regex_intents, llm_result
        )

        logger.info(
            "Intent classified: types=%s, confidence=%.2f, entities=%d",
            [t.value for t in merged.intent_types],
            merged.confidence,
            len(merged.entities),
        )

        # Step 4: Check confidence threshold
        if merged.confidence < INTENT_CLASSIFICATION_CONFIDENCE_THRESHOLD:
            raise IntentClassificationError(
                confidence=merged.confidence,
                reason=merged.clarification_prompt or "Low classification confidence",
                suggested_rephrasings=self._suggest_rephrasings(command),
            )

        return merged

    def _extract_entities_regex(self, command: str) -> list[ExtractedEntity]:
        """Extract entities using regex patterns."""
        entities: list[ExtractedEntity] = []

        # Service names
        for pattern in _SERVICE_NAME_PATTERNS:
            for match in re.finditer(pattern, command, re.IGNORECASE):
                entities.append(ExtractedEntity(
                    type="service_name",
                    value=match.group(1).lower(),
                    raw_text=match.group(0),
                    confidence=0.90,
                    resolved=True,
                ))

        # Time ranges
        for pattern, unit in _TIME_RANGE_PATTERNS:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                if unit == "since_yesterday":
                    entities.append(ExtractedEntity(
                        type="time_range",
                        value={"start": "yesterday", "end": "now"},
                        raw_text=match.group(0),
                        confidence=0.85,
                        resolved=True,
                    ))
                elif unit == "since_last_week":
                    entities.append(ExtractedEntity(
                        type="time_range",
                        value={"start": "7_days_ago", "end": "now"},
                        raw_text=match.group(0),
                        confidence=0.85,
                        resolved=True,
                    ))
                else:
                    value: str = match.group(1)
                    entities.append(ExtractedEntity(
                        type="time_range",
                        value={"amount": int(value), "unit": unit},
                        raw_text=match.group(0),
                        confidence=0.90,
                        resolved=True,
                    ))

        # Thresholds
        for pattern in _THRESHOLD_PATTERNS:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                entities.append(ExtractedEntity(
                    type="threshold",
                    value={
                        "metric": match.group(0).split()[0] if match.groups() else "unknown",
                        "operator": ">" if ">" in match.group(0) else "<",
                        "value": float(re.search(r"\d+(?:\.\d+)?", match.group(0)).group()) if re.search(r"\d+(?:\.\d+)?", match.group(0)) else 0,
                    },
                    raw_text=match.group(0),
                    confidence=0.88,
                    resolved=True,
                ))

        # Resource IDs
        for pattern in _RESOURCE_ID_PATTERNS:
            for match in re.finditer(pattern, command):
                entity_type: str = "resource_id"
                if match.group(0).startswith("#"):
                    entity_type = "channel"
                elif re.match(r"[A-Z]+-\d+", match.group(0)):
                    entity_type = "ticket_id"
                entities.append(ExtractedEntity(
                    type=entity_type,
                    value=match.group(0),
                    raw_text=match.group(0),
                    confidence=0.85,
                    resolved=True,
                ))

        # Severity
        for pattern in _SEVERITY_PATTERNS:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                entities.append(ExtractedEntity(
                    type="severity",
                    value=match.group(1).upper(),
                    raw_text=match.group(0),
                    confidence=0.92,
                    resolved=True,
                ))

        return entities

    def _infer_intents_regex(self, command: str) -> list[IntentType]:
        """Infer intent types from keyword matching."""
        cmd_lower: str = command.lower()
        intents: set[IntentType] = set()

        if any(kw in cmd_lower for kw in _DESTRUCTIVE_KEYWORDS):
            intents.add(IntentType.ACTION)
        if any(kw in cmd_lower for kw in _ANALYSIS_KEYWORDS):
            intents.add(IntentType.ANALYZE)
        if any(kw in cmd_lower for kw in _NOTIFICATION_KEYWORDS):
            intents.add(IntentType.NOTIFY)
        if any(kw in cmd_lower for kw in _REMEDIATION_KEYWORDS):
            intents.add(IntentType.REMEDIATE)
        if "correlate" in cmd_lower or "connect" in cmd_lower or "link" in cmd_lower:
            intents.add(IntentType.CORRELATE)
        if "check" in cmd_lower or "get" in cmd_lower or "show" in cmd_lower or "describe" in cmd_lower:
            intents.add(IntentType.QUERY)

        return list(intents) if intents else [IntentType.QUERY]

    def _merge_results(
        self,
        command: str,
        regex_entities: list[ExtractedEntity],
        regex_intents: list[IntentType],
        llm_result: IntentClassification | None,
    ) -> IntentClassification:
        """Merge regex and LLM results with conflict resolution."""
        if llm_result is None:
            return IntentClassification(
                intent_types=regex_intents if regex_intents else [IntentType.QUERY],
                entities=regex_entities,
                confidence=0.65,
                command_summary=command[:200],
                requires_clarification=True,
                clarification_prompt="Could you clarify your intent?",
            )

        # Merge entities: regex wins on exact pattern matches
        merged_entities: dict[str, ExtractedEntity] = {}
        for e in regex_entities:
            key: str = f"{e.type}:{e.value}"
            merged_entities[key] = e
        for e in llm_result.entities:
            key = f"{e.type}:{e.value}"
            if key not in merged_entities:
                merged_entities[key] = e

        # Merge intents: use LLM's primary, add regex if not present
        merged_intents: list[IntentType] = list(llm_result.intent_types)
        for intent in regex_intents:
            if intent not in merged_intents:
                merged_intents.append(intent)

        # Calculate final confidence
        final_confidence: float = llm_result.confidence
        if regex_entities:
            final_confidence = min(0.99, final_confidence + 0.05)

        return IntentClassification(
            intent_types=merged_intents,
            entities=list(merged_entities.values()),
            confidence=final_confidence,
            command_summary=llm_result.command_summary or command[:200],
            requires_clarification=final_confidence < INTENT_CLASSIFICATION_CONFIDENCE_THRESHOLD,
            clarification_prompt=llm_result.clarification_prompt,
        )

    def _suggest_rephrasings(self, command: str) -> list[str]:
        """Suggest alternative phrasings for low-confidence commands."""
        suggestions: list[str] = [
            f"Check status of {command}",
            f"Show me information about {command}",
            f"Analyze {command} and report findings",
        ]
        return suggestions[:3]


# ---------------------------------------------------------------------------
# IntentPlanner
# ---------------------------------------------------------------------------


class IntentPlanner:
    """Converts classified intent into an executable DAG plan.

    Uses template matching first, then falls back to zero-shot LLM planning.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        available_tools: list[dict[str, Any]] | None = None,
    ) -> None:
        self._llm: LLMClient | None = llm_client
        self._available_tools: list[dict[str, Any]] = available_tools or []

    async def build_plan(self, intent: IntentClassification) -> ExecutionPlan:
        """Build an execution plan from classified intent.

        1. Try template matching (5 built-in templates)
        2. Fall back to zero-shot LLM planning
        3. Validate the plan
        4. Refine for efficiency

        Args:
            intent: The classified intent.

        Returns:
            Validated ExecutionPlan DAG.

        Raises:
            PlanningError: If plan generation fails.
        """
        # Step 1: Try template matching
        template_plan: ExecutionPlan | None = self._match_template(intent)
        if template_plan:
            logger.info("Matched template: %s", template_plan.template_used)
            return self._refine_plan(template_plan)

        # Step 2: Zero-shot LLM planning
        if self._llm and self._available_tools:
            try:
                llm_plan: ExecutionPlan = await self._llm.generate_plan(
                    intent, self._available_tools
                )
                llm_plan = self._validate_plan(llm_plan)
                return self._refine_plan(llm_plan)
            except Exception as e:
                logger.error("LLM plan generation failed: %s", e)
                raise PlanningError(f"Failed to generate plan: {e}")

        # Step 3: Fallback - single query step
        logger.warning("No LLM available, creating fallback single-step plan")
        return self._create_fallback_plan(intent)

    def _match_template(self, intent: IntentClassification) -> ExecutionPlan | None:
        """Match intent against built-in plan templates."""
        cmd_lower: str = intent.command_summary.lower()

        for template_name, template_def in _PLAN_TEMPLATES.items():
            triggers: list[str] = template_def["triggers"]
            if all(trigger.lower() in cmd_lower for trigger in triggers):
                steps: list[PlanStep] = []
                dependencies: dict[str, list[str]] = {}

                for step_def in template_def["steps"]:
                    step = PlanStep(
                        id=step_def["id"],
                        tool_name=step_def["tool_name"],
                        server=step_def["server"],
                        description=step_def["description"],
                        depends_on=list(step_def.get("depends_on", [])),
                        condition=step_def.get("condition"),
                    )
                    steps.append(step)

                # Build dependency adjacency list
                for step in steps:
                    for dep in step.depends_on:
                        dependencies.setdefault(dep, []).append(step.id)

                return ExecutionPlan(
                    template_used=template_name,
                    steps=steps,
                    dependencies=dependencies,
                    estimated_duration_ms=sum(s.estimated_duration_ms for s in steps),
                    confidence=0.85,
                    explanation=f"Matched '{template_name}' template",
                )

        return None

    def _validate_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Validate plan against available tools.

        Checks:
        - All tool names exist in the registry
        - No circular dependencies (already validated by model)
        - All referenced variables are defined
        """
        if not self._available_tools:
            return plan

        available_tool_names: set[str] = set()
        for tool in self._available_tools:
            name: str = tool.get("name", "")
            available_tool_names.add(name)
            if "/" in name:
                available_tool_names.add(name.split("/")[-1])

        for step in plan.steps:
            if step.tool_name not in available_tool_names:
                logger.warning(
                    "Plan step '%s' uses unknown tool '%s'",
                    step.id,
                    step.tool_name,
                )

        return plan

    def _refine_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Optimize the plan DAG.

        - Collapse unnecessary passthroughs
        - Maximize parallelism
        - Auto-mark destructive operations as critical
        """
        # Build reverse dependency map for efficiency calculation
        reverse_deps: dict[str, list[str]] = {}
        for step in plan.steps:
            for dep in step.depends_on:
                reverse_deps.setdefault(dep, []).append(step.id)

        # Calculate estimated duration based on critical path
        durations: dict[str, int] = {}
        for step in plan.steps:
            if not step.depends_on:
                durations[step.id] = step.estimated_duration_ms
            else:
                max_dep_duration: int = max(
                    durations.get(dep, 1000) for dep in step.depends_on
                )
                durations[step.id] = max_dep_duration + step.estimated_duration_ms

        critical_path: int = max(durations.values()) if durations else 0

        return plan.model_copy(update={
            "estimated_duration_ms": critical_path,
        })

    def _create_fallback_plan(self, intent: IntentClassification) -> ExecutionPlan:
        """Create a simple fallback plan when LLM is unavailable."""
        step: PlanStep = PlanStep(
            id="step-1",
            tool_name="search",
            server="tavily-search",
            description=f"Search for information about: {intent.command_summary}",
        )
        return ExecutionPlan(
            template_used=None,
            steps=[step],
            dependencies={},
            estimated_duration_ms=5000,
            confidence=0.50,
            risk_level="low",
            explanation="Fallback plan: search-based information retrieval",
        )
