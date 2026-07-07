"""OpenAI client wrapper for mcp-opsmate.

Provides async methods for intent classification and plan generation
with retry logic, structured JSON mode, and comprehensive error handling.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from opsmate.core.config import get_config
from opsmate.core.constants import DEFAULT_TEMPERATURE
from opsmate.core.exceptions import PlanningError
from opsmate.core.models import ExecutionPlan, IntentClassification, derive_seed

logger: logging.Logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_CLASSIFICATION_SYSTEM_PROMPT: str = """\
You are an infrastructure operations intent classifier.
Your job is to analyze natural language commands from DevOps/SRE engineers
and classify them into intent categories with high confidence.

Classify the command into one or more of these intent types:
- query: Information retrieval (status, logs, metrics)
- action: Execute a command or operation (restart, deploy, scale)
- analyze: Comparative or diagnostic analysis
- notify: Send alerts or notifications
- correlate: Connect events across systems (CI failure -> incident ticket)
- remediate: Fix an identified problem automatically

Extract entities like: service_name, time_range, threshold, resource_id, severity, channel.

Respond in JSON format with these fields:
{
    "intent_types": ["query"],
    "entities": [
        {"type": "service_name", "value": "payment-service", "raw_text": "payment service", "confidence": 0.95, "resolved": true}
    ],
    "confidence": 0.92,
    "command_summary": "Check payment service health and restart if needed",
    "requires_clarification": false,
    "clarification_prompt": null
}

## Few-Shot Examples

Example 1 - Health Check:
Command: "Check payment-service pods in EKS, restart if CPU > 80%"
→ intent_types: ["query", "action"], entities: [{service_name: "payment-service"}, {threshold: "CPU > 80%"}], confidence: 0.95

Example 2 - Incident Response:
Command: "Find P0 incidents in JIRA from last 24h and post summary to #incidents"
→ intent_types: ["query", "correlate", "notify"], entities: [{severity: "P0"}, {time_range: "last 24h"}, {channel: "#incidents"}], confidence: 0.92

Example 3 - Deployment Validation:
Command: "Verify the deployment of api-gateway v2.1.0"
→ intent_types: ["query", "analyze"], entities: [{service_name: "api-gateway"}, {resource_id: "v2.1.0"}], confidence: 0.88

Example 4 - Cost Analysis:
Command: "Compare Lambda costs between us-east-1 and eu-west-1 for the last 7 days"
→ intent_types: ["analyze"], entities: [{resource_id: "Lambda"}, {time_range: "last 7 days"}], confidence: 0.90

Example 5 - Performance Analysis:
Command: "Check if database latency is above 100ms and alert #db-team"
→ intent_types: ["query", "notify"], entities: [{threshold: "latency > 100ms"}, {channel: "#db-team"}], confidence: 0.93

Example 6 - CI Correlation:
Command: "The build failed for user-service, check if there's an open incident"
→ intent_types: ["correlate", "query"], entities: [{service_name: "user-service"}], confidence: 0.85

Example 7 - Remediation:
Command: "Auto-remediate CrashLoopBackOff pods in the default namespace"
→ intent_types: ["remediate", "action"], entities: [{resource_id: "CrashLoopBackOff"}, {service_name: "default namespace"}], confidence: 0.91

Example 8 - Correlation:
Command: "Correlate the failed GitHub workflow with any JIRA tickets and Slack alerts"
→ intent_types: ["correlate", "query"], entities: [], confidence: 0.87
"""

_PLANNING_SYSTEM_PROMPT_TEMPLATE: str = """\
You are an infrastructure automation planner. You convert classified intents
into execution plans as directed acyclic graphs (DAGs).

Given the user's classified intent and available tools, generate an ExecutionPlan in JSON format.

## Available Tools
{tool_schemas}

## Response Format
Respond with a JSON object:
{{
    "steps": [
        {{
            "id": "step-1",
            "tool_name": "describe_pods",
            "server": "aws-ecs",
            "description": "Get pod status for the service",
            "input_mapping": {{"namespace": "{{context.namespace}}", "service": "{{context.service_name}}"}},
            "depends_on": [],
            "critical": false,
            "condition": null
        }}
    ],
    "dependencies": {{"step-1": ["step-2"]}},
    "estimated_duration_ms": 5000,
    "confidence": 0.90,
    "explanation": "First check pod status, then get metrics if needed"
}}

Rules:
1. Every tool_name must be from the available tools list above.
2. Dependencies must form a valid DAG (no cycles).
3. Use depends_on to specify prerequisites, not the dependencies field.
4. The dependencies field is the adjacency list {step_id -> [dependents]}.
5. Mark destructive operations (restart, delete) as critical: true.
6. Use Jinja2-like templates in input_mapping: "{{step_id.output_field}}".
7. Keep confidence realistic based on intent clarity.
8. Minimize steps - collapse unnecessary intermediates.
9. Maximize parallelism where steps have no dependencies.
"""


class LLMClient:
    """Async OpenAI client wrapper for opsmate.

    Provides structured output generation with retry logic,
    temperature control, and comprehensive error handling.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = 4096,
        planning_timeout_ms: int = 5000,
        max_retries: int = 3,
    ) -> None:
        self.api_key: str = api_key or ""
        self.model: str = model
        self.temperature: float = temperature
        self.max_tokens: int = max_tokens
        self.planning_timeout_ms: int = planning_timeout_ms
        self.max_retries: int = max_retries
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Lazily initialize the OpenAI client."""
        if self._client is None:
            try:
                import openai

                self._client = openai.AsyncOpenAI(
                    api_key=self.api_key,
                    timeout=self.planning_timeout_ms / 1000 + 10,
                )
            except ImportError:
                raise PlanningError("openai package not installed")
        return self._client

    async def _generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """Generate completion with exponential backoff retry.

        Args:
            system_prompt: System prompt for the LLM.
            user_prompt: User prompt for the LLM.
            temperature: Override temperature for this call.
            max_tokens: Override max_tokens for this call.
            response_format: OpenAI response format specification.

        Returns:
            Generated text content.

        Raises:
            PlanningError: After all retries are exhausted.
        """
        client = self._get_client()
        temp: float = temperature if temperature is not None else self.temperature
        tokens: int = max_tokens if max_tokens is not None else self.max_tokens

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await client.chat.completions.create(**kwargs)
                content: str = response.choices[0].message.content or ""
                return content
            except Exception as e:
                last_error = e
                wait_time: float = 2 ** (attempt - 1)  # exponential backoff: 1s, 2s, 4s
                logger.warning(
                    "LLM generation attempt %d/%d failed: %s. Retrying in %.1fs",
                    attempt,
                    self.max_retries,
                    e,
                    wait_time,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(wait_time)

        raise PlanningError(
            f"LLM generation failed after {self.max_retries} attempts: {last_error}",
            details={"last_error": str(last_error)},
        )

    async def classify_intent(self, command: str) -> IntentClassification:
        """Classify a natural language command into intent categories.

        Args:
            command: The user's natural language command.

        Returns:
            IntentClassification with types, entities, and confidence.

        Raises:
            PlanningError: If classification fails after retries.
        """
        try:
            content: str = await self._generate_with_retry(
                system_prompt=_CLASSIFICATION_SYSTEM_PROMPT,
                user_prompt=f"Classify this command:\n\n{command}",
                response_format={"type": "json_object"},
            )
            data: dict[str, Any] = json.loads(content)
            classification: IntentClassification = (
                IntentClassification.model_validate(data)
            )
            logger.info(
                "Intent classified: types=%s, confidence=%.2f",
                [t.value for t in classification.intent_types],
                classification.confidence,
            )
            return classification
        except json.JSONDecodeError as e:
            raise PlanningError(f"Invalid JSON from LLM: {e}")
        except Exception as e:
            raise PlanningError(f"Intent classification failed: {e}")

    async def generate_plan(
        self,
        intent: IntentClassification,
        available_tools: list[dict[str, Any]],
    ) -> ExecutionPlan:
        """Generate an execution plan from a classified intent.

        Args:
            intent: The classified intent from classify_intent().
            available_tools: List of available tool schemas from the ToolRegistry.

        Returns:
            ExecutionPlan DAG with steps, dependencies, and risk assessment.

        Raises:
            PlanningError: If plan generation fails after retries.
        """
        tool_schema_text: str = json.dumps(available_tools, indent=2)
        system_prompt: str = _PLANNING_SYSTEM_PROMPT_TEMPLATE.format(
            tool_schemas=tool_schema_text
        )
        user_prompt: str = (
            f"Command summary: {intent.command_summary}\n"
            f"Intent types: {[t.value for t in intent.intent_types]}\n"
            f"Entities: {[e.model_dump() for e in intent.entities]}\n"
            f"Confidence: {intent.confidence}"
        )

        last_error: Exception | None = None
        for attempt in range(1, min(3, self.max_retries) + 1):
            try:
                content: str = await self._generate_with_retry(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format={"type": "json_object"},
                )
                data: dict[str, Any] = json.loads(content)
                plan: ExecutionPlan = ExecutionPlan.model_validate(data)
                logger.info(
                    "Plan generated: %d steps, template=%s, risk=%s",
                    len(plan.steps),
                    plan.template_used,
                    plan.risk_level.value,
                )
                return plan
            except Exception as e:
                last_error = e
                logger.warning(
                    "Plan generation attempt %d/3 failed: %s",
                    attempt,
                    e,
                )
                if attempt < 3:
                    await asyncio.sleep(1)

        raise PlanningError(
            f"Plan generation failed: {last_error}",
            details={"intent": intent.model_dump()},
        )

    async def generate_response(self, prompt: str, *, temperature: float = 0.7) -> str:
        """Generate a general-purpose LLM response.

        Args:
            prompt: The user prompt.
            temperature: Temperature override (higher = more creative).

        Returns:
            Generated text.
        """
        content: str = await self._generate_with_retry(
            system_prompt="You are a helpful DevOps assistant.",
            user_prompt=prompt,
            temperature=temperature,
        )
        return content


def create_llm_client_from_config() -> LLMClient:
    """Factory to create an LLMClient from the global config."""
    config = get_config()
    return LLMClient(
        api_key=config.llm.api_key,
        model=config.llm.model,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
        planning_timeout_ms=config.llm.planning_timeout_ms,
    )
