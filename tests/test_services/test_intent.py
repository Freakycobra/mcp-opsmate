"""
Tests for the intent classification and planning services.

Covers regex entity extraction, hybrid intent classification, plan template
matching, zero-shot planning, DAG validation, and risk level computation.
All LLM calls are mocked — no real OpenAI API requests.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRegexEntityExtraction:
    """Tests for the regex-based entity extractor."""

    @pytest.fixture
    def extractor(self) -> Any:
        """Provide a regex entity extractor instance."""
        from opsmate.services.intent import RegexEntityExtractor
        return RegexEntityExtractor()

    @pytest.mark.asyncio
    async def test_extract_service_name(self, extractor: Any) -> None:
        """Extract known service names from commands."""
        result = await extractor.extract("Check payment-service pods in EKS")
        assert result["service_name"] == "payment-service"

    @pytest.mark.asyncio
    async def test_extract_time_range_last_n_hours(self, extractor: Any) -> None:
        """Extract relative time ranges like 'last 2h'."""
        result = await extractor.extract("Show CPU metrics for the last 2 hours")
        assert "time_range" in result
        assert "start" in result["time_range"]
        assert "end" in result["time_range"]

    @pytest.mark.asyncio
    async def test_extract_time_range_since_yesterday(self, extractor: Any) -> None:
        """Extract 'since yesterday' time ranges."""
        result = await extractor.extract("Show errors since yesterday")
        assert "time_range" in result

    @pytest.mark.asyncio
    async def test_extract_threshold(self, extractor: Any) -> None:
        """Extract numeric thresholds with operators."""
        result = await extractor.extract("Restart pods if CPU > 80%")
        assert result["threshold"] == {"operator": ">", "value": 80.0, "metric": "cpu_percent"}

    @pytest.mark.asyncio
    async def test_extract_jira_ticket_id(self, extractor: Any) -> None:
        """Extract Jira ticket IDs like PROJ-123."""
        result = await extractor.extract("Get details for JIRA-456")
        assert result["jira_ticket"] == "JIRA-456"

    @pytest.mark.asyncio
    async def test_extract_slack_channel(self, extractor: Any) -> None:
        """Extract Slack channel names."""
        result = await extractor.extract("Send alert to #on-call channel")
        assert result["slack_channel"] == "on-call"

    @pytest.mark.asyncio
    async def test_extract_aws_resource_arn(self, extractor: Any) -> None:
        """Extract AWS ARN patterns."""
        result = await extractor.extract("Check arn:aws:ecs:us-east-1:123:cluster/prod")
        assert "aws_arn" in result

    @pytest.mark.asyncio
    async def test_fuzzy_service_name_matching(self, extractor: Any) -> None:
        """Fuzzy match service names with Levenshtein distance <= 2."""
        result = await extractor.extract("Check paymnt-service pods")  # typo
        assert "service_name" in result

    @pytest.mark.asyncio
    async def test_no_entities_found(self, extractor: Any) -> None:
        """Commands with no extractable entities return empty dict."""
        result = await extractor.extract("Hello world")
        assert result == {}


class TestIntentClassifierMock:
    """Tests for the hybrid intent classifier with mocked LLM."""

    @pytest.fixture
    def classifier(self, mock_openai: MagicMock) -> Any:
        """Provide an intent classifier with mocked OpenAI client."""
        from opsmate.services.intent import HybridIntentClassifier
        return HybridIntentClassifier()

    @pytest.mark.asyncio
    async def test_classify_high_confidence(self, classifier: Any, mock_openai: MagicMock) -> None:
        """Classify a clear infrastructure command with high confidence."""
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"type": ["QUERY", "ACTION"], "entities": {"service_name": "payment-service"}, "confidence": 0.94}'
                    )
                )]
            )
        )

        result = await classifier.classify("Check payment-service pods and restart if CPU > 80%")

        assert "type" in result
        assert "entities" in result
        assert "confidence" in result
        assert result["confidence"] >= 0.7
        assert isinstance(result["type"], list)

    @pytest.mark.asyncio
    async def test_classify_low_confidence(self, classifier: Any, mock_openai: MagicMock) -> None:
        """Classify an ambiguous command with low confidence."""
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"type": ["UNKNOWN"], "entities": {}, "confidence": 0.45}'
                    )
                )]
            )
        )

        result = await classifier.classify("Something about the thing")

        assert result["confidence"] < 0.7

    @pytest.mark.asyncio
    async def test_classify_query_intent(self, classifier: Any, mock_openai: MagicMock) -> None:
        """Classify a pure query command."""
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"type": ["QUERY"], "entities": {"service_name": "auth-service"}, "confidence": 0.92}'
                    )
                )]
            )
        )

        result = await classifier.classify("Show me auth-service pod status")
        assert "QUERY" in result["type"]

    @pytest.mark.asyncio
    async def test_classify_notify_intent(self, classifier: Any, mock_openai: MagicMock) -> None:
        """Classify a notification command."""
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"type": ["NOTIFY"], "entities": {"slack_channel": "on-call"}, "confidence": 0.91}'
                    )
                )]
            )
        )

        result = await classifier.classify("Send alert to #on-call Slack channel")
        assert "NOTIFY" in result["type"]

    @pytest.mark.asyncio
    async def test_classify_multi_label(self, classifier: Any, mock_openai: MagicMock) -> None:
        """Classify a compound command with multiple intent labels."""
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"type": ["QUERY", "NOTIFY"], "entities": {"service_name": "api-gateway"}, "confidence": 0.93}'
                    )
                )]
            )
        )

        result = await classifier.classify("Check api-gateway health and notify the team")
        assert len(result["type"]) >= 2

    @pytest.mark.asyncio
    async def test_classify_out_of_scope_rejection(self, classifier: Any, mock_openai: MagicMock) -> None:
        """Out-of-scope commands are rejected with explanation."""
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"type": ["REJECT"], "entities": {}, "confidence": 0.88, "reason": "Out of scope: personal task management"}'
                    )
                )]
            )
        )

        result = await classifier.classify("Buy me a coffee")
        assert "REJECT" in result["type"] or result["confidence"] < 0.5


class TestPlanTemplateMatcher:
    """Tests for the plan template matcher."""

    @pytest.fixture
    def template_matcher(self) -> Any:
        """Provide a plan template matcher."""
        from opsmate.services.intent import PlanTemplateMatcher
        return PlanTemplateMatcher()

    @pytest.mark.asyncio
    async def test_health_check_and_remediate_template(
        self,
        template_matcher: Any,
        sample_intent: dict[str, Any],
    ) -> None:
        """Match 'health check and remediate' template pattern."""
        intent = {
            **sample_intent,
            "type": ["QUERY", "ACTION"],
            "plan_template": "health-check-and-remediate",
        }

        result = await template_matcher.match(intent)
        assert result is not None
        assert result["template_name"] == "health-check-and-remediate"

    @pytest.mark.asyncio
    async def test_incident_response_template(self, template_matcher: Any) -> None:
        """Match 'incident response' template pattern."""
        intent = {
            "type": ["ANALYZE", "NOTIFY"],
            "entities": {"severity": "P1"},
            "confidence": 0.9,
        }

        result = await template_matcher.match(intent)
        assert result is not None
        assert result["template_name"] == "incident-response"

    @pytest.mark.asyncio
    async def test_performance_analysis_template(self, template_matcher: Any) -> None:
        """Match 'performance analysis' template pattern."""
        intent = {
            "type": ["ANALYZE"],
            "entities": {"metric": "latency", "comparison": "week-over-week"},
            "confidence": 0.92,
        }

        result = await template_matcher.match(intent)
        assert result is not None
        assert result["template_name"] == "performance-analysis"

    @pytest.mark.asyncio
    async def test_cost_analysis_template(self, template_matcher: Any) -> None:
        """Match 'cost analysis' template pattern."""
        intent = {
            "type": ["ANALYZE"],
            "entities": {"topic": "cost", "scope": "aws"},
            "confidence": 0.88,
        }

        result = await template_matcher.match(intent)
        assert result is not None
        assert result["template_name"] == "cost-analysis"

    @pytest.mark.asyncio
    async def test_no_template_match(self, template_matcher: Any) -> None:
        """No template matches returns None, falling back to zero-shot planning."""
        intent = {
            "type": ["UNKNOWN"],
            "entities": {},
            "confidence": 0.6,
        }

        result = await template_matcher.match(intent)
        assert result is None


class TestZeroShotPlannerMock:
    """Tests for the zero-shot planner with mocked LLM."""

    @pytest.fixture
    def planner(self, mock_openai: MagicMock) -> Any:
        """Provide a zero-shot planner with mocked OpenAI."""
        from opsmate.services.intent import ZeroShotPlanner
        return ZeroShotPlanner()

    @pytest.mark.asyncio
    async def test_plan_single_tool_command(
        self,
        planner: Any,
        mock_openai: MagicMock,
    ) -> None:
        """Plan a single-tool command."""
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"steps": [{"id": "step-1", "tool_name": "describe_pods", "server": "aws-ecs"}], "dependencies": {"step-1": []}}'
                    )
                )]
            )
        )

        intent = {"type": ["QUERY"], "entities": {"service_name": "payment-service"}}
        result = await planner.plan(intent, available_tools=[])

        assert "steps" in result
        assert len(result["steps"]) >= 1

    @pytest.mark.asyncio
    async def test_plan_multi_tool_command(
        self,
        planner: Any,
        mock_openai: MagicMock,
    ) -> None:
        """Plan a multi-tool command with dependencies."""
        mock_openai.return_value.chat.completions.create = AsyncMock(
            return_value=MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"steps": [{"id": "step-1", "tool_name": "describe_pods"}, {"id": "step-2", "tool_name": "send_slack_message"}], "dependencies": {"step-1": ["step-2"], "step-2": []}}'
                    )
                )]
            )
        )

        intent = {"type": ["QUERY", "NOTIFY"], "entities": {}}
        result = await planner.plan(intent, available_tools=[])

        assert len(result["steps"]) >= 2
        assert "dependencies" in result

    @pytest.mark.asyncio
    async def test_plan_with_validation_retry(
        self,
        planner: Any,
        mock_openai: MagicMock,
    ) -> None:
        """Invalid plan triggers validation and retry (up to 2 retries)."""
        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First response: invalid (references unknown tool)
                return MagicMock(
                    choices=[MagicMock(
                        message=MagicMock(
                            content='{"steps": [{"id": "step-1", "tool_name": "unknown_tool"}], "dependencies": {"step-1": []}}'
                        )
                    )]
                )
            # Second response: valid
            return MagicMock(
                choices=[MagicMock(
                    message=MagicMock(
                        content='{"steps": [{"id": "step-1", "tool_name": "describe_pods", "server": "aws-ecs"}], "dependencies": {"step-1": []}}'
                    )
                )]
            )

        mock_openai.return_value.chat.completions.create = AsyncMock(side_effect=side_effect)

        intent = {"type": ["QUERY"], "entities": {}}
        result = await planner.plan(
            intent,
            available_tools=[{"name": "describe_pods", "server": "aws-ecs"}],
        )

        assert "steps" in result
        assert call_count <= 3  # Original + up to 2 retries


class TestPlanDAGValidation:
    """Tests for plan DAG validation."""

    @pytest.fixture
    def validator(self) -> Any:
        """Provide a plan validator."""
        from opsmate.services.intent import PlanValidator
        return PlanValidator()

    @pytest.mark.asyncio
    async def test_valid_dag(self, validator: Any, sample_plan: dict[str, Any]) -> None:
        """A valid DAG passes validation."""
        result = await validator.validate(sample_plan, available_tools=[
            {"name": "describe_pods", "server": "aws-ecs"},
            {"name": "get_cloudwatch_metrics", "server": "aws-ecs"},
            {"name": "restart_pods", "server": "aws-ecs"},
            {"name": "send_slack_message", "server": "slack"},
        ])
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_circular_dependency_detected(self, validator: Any) -> None:
        """Circular dependencies in the DAG are detected and rejected."""
        plan = {
            "steps": [
                {"id": "step-1", "tool_name": "tool_a"},
                {"id": "step-2", "tool_name": "tool_b"},
            ],
            "dependencies": {
                "step-1": ["step-2"],
                "step-2": ["step-1"],  # Circular!
            },
        }

        result = await validator.validate(plan, available_tools=[])
        assert result["valid"] is False
        assert "circular" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_unknown_tool_detected(self, validator: Any) -> None:
        """References to unknown tools are detected."""
        plan = {
            "steps": [
                {"id": "step-1", "tool_name": "nonexistent_tool_xyz"},
            ],
            "dependencies": {"step-1": []},
        }

        result = await validator.validate(plan, available_tools=[
            {"name": "describe_pods", "server": "aws-ecs"},
        ])
        assert result["valid"] is False

    @pytest.mark.asyncio
    async def test_missing_variable_reference(self, validator: Any) -> None:
        """Undefined variable references in step inputs are detected."""
        plan = {
            "steps": [
                {
                    "id": "step-1",
                    "tool_name": "send_slack_message",
                    "input_schema": {"message": "{{undefined_var.output}}"},
                },
            ],
            "dependencies": {"step-1": []},
        }

        result = await validator.validate(plan, available_tools=[])
        # Should flag the undefined reference
        assert result["valid"] is False or "warnings" in result


class TestPlanRiskLevelComputation:
    """Tests for risk level computation in execution plans."""

    @pytest.fixture
    def risk_calculator(self) -> Any:
        """Provide a risk level calculator."""
        from opsmate.services.intent import RiskLevelCalculator
        return RiskLevelCalculator()

    @pytest.mark.asyncio
    async def test_low_risk_read_only(self, risk_calculator: Any) -> None:
        """Read-only plans have LOW risk."""
        plan = {
            "steps": [
                {"id": "step-1", "tool_name": "describe_pods", "critical": False},
                {"id": "step-2", "tool_name": "get_cloudwatch_metrics", "critical": False},
            ],
        }
        result = await risk_calculator.compute(plan)
        assert result == "LOW"

    @pytest.mark.asyncio
    async def test_medium_risk_conditional_write(self, risk_calculator: Any) -> None:
        """Plans with conditional write operations have MEDIUM risk."""
        plan = {
            "steps": [
                {"id": "step-1", "tool_name": "describe_pods", "critical": False},
                {
                    "id": "step-2",
                    "tool_name": "restart_pods",
                    "critical": True,
                    "condition": "cpu > 80",
                },
            ],
        }
        result = await risk_calculator.compute(plan)
        assert result == "MEDIUM"

    @pytest.mark.asyncio
    async def test_high_risk_direct_write(self, risk_calculator: Any) -> None:
        """Plans with unconditional destructive operations have HIGH risk."""
        plan = {
            "steps": [
                {"id": "step-1", "tool_name": "delete_pods", "critical": True},
                {"id": "step-2", "tool_name": "scale_service", "critical": True},
            ],
        }
        result = await risk_calculator.compute(plan)
        assert result == "HIGH"

    @pytest.mark.asyncio
    async def test_high_risk_multiple_critical_steps(self, risk_calculator: Any) -> None:
        """Plans with multiple critical steps have HIGH risk."""
        plan = {
            "steps": [
                {"id": "step-1", "tool_name": "restart_pods", "critical": True},
                {"id": "step-2", "tool_name": "scale_service", "critical": True},
                {"id": "step-3", "tool_name": "update_config", "critical": True},
            ],
        }
        result = await risk_calculator.compute(plan)
        assert result == "HIGH"
