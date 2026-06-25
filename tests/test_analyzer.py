"""
POV-4: Unit tests for the Performance Analysis Agent and LLM Provider layers.
"""

import pytest
from uuid import UUID, uuid4
from typing import Any, Dict, List, Optional, Type
from unittest.mock import MagicMock, patch
from pydantic import BaseModel, ValidationError

from src.core.config import get_settings, Settings
from src.domain.enums import IssueSeverity, IssueType, EvidenceQuality
from src.domain.models import AnalysisResult, DetectedIssue, Recommendation, TelemetrySnapshot
from src.agents.providers import (
    LLMProvider,
    GeminiProvider,
    LLMAnalysisError,
    LLMProviderError,
    LLMTimeoutError,
    LLMValidationError,
)
from src.agents.analyzer import (
    QueryPerformanceAnalyzer,
    prune_operator_stats,
    load_prompt_templates,
)


# ---------------------------------------------------------------------------
# Mock Provider
# ---------------------------------------------------------------------------

class MockLLMProvider(LLMProvider):
    def __init__(
        self, 
        return_value: Optional[Dict[str, Any]] = None, 
        exception_to_raise: Optional[Exception] = None, 
        raise_n_times: int = 0
    ):
        self.return_value = return_value
        self.exception_to_raise = exception_to_raise
        self.raise_n_times = raise_n_times
        self.call_count = 0
        self.invoked_args = []

    def generate(
        self,
        system_instruction: str,
        user_prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        temperature: float = 0.0,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any] | str:
        self.call_count += 1
        self.invoked_args.append({
            "system_instruction": system_instruction,
            "user_prompt": user_prompt,
            "response_schema": response_schema,
            "temperature": temperature,
            "timeout_seconds": timeout_seconds
        })
        if self.exception_to_raise and self.call_count <= self.raise_n_times:
            raise self.exception_to_raise
        return self.return_value if self.return_value is not None else {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_settings() -> Settings:
    settings = get_settings()
    # Force settings overrides for test isolation
    settings.gemini.api_key = "mock-api-key"
    settings.gemini.model_name = "gemini-3.5-flash"
    settings.gemini.max_retries = 2
    settings.gemini.request_timeout_seconds = 5
    settings.gemini.prompt_version = "v1_default"
    return settings


@pytest.fixture()
def mock_telemetry_snapshot() -> TelemetrySnapshot:
    return TelemetrySnapshot(
        snapshot_id=uuid4(),
        timestamp=pytest.importorskip("datetime").datetime.now(pytest.importorskip("datetime").timezone.utc),
        query_id="mock-query-id-123",
        warehouse_name="MOCK_WH",
        query_history={
            "QUERY_ID": "mock-query-id-123",
            "WAREHOUSE_NAME": "MOCK_WH",
            "WAREHOUSE_SIZE": "SMALL",
            "EXECUTION_TIME": 15000,
            "ROWS_PRODUCED": 500000,
            "BYTES_SCANNED": 1048576,
            "PARTITIONS_SCANNED": 10,
            "PARTITIONS_TOTAL": 10
        },
        warehouse_load={"AVG_RUNNING": 0.5, "AVG_QUEUED_LOAD": 0.0},
        metering_context={"CREDITS_USED_COMPUTE": 0.02},
        query_attribution={"CREDITS_USED_COMPUTE": 0.01}
    )


@pytest.fixture()
def mock_detected_issues(mock_telemetry_snapshot) -> List[DetectedIssue]:
    return [
        DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.POOR_PARTITION_PRUNING,
            severity=IssueSeverity.MEDIUM,
            threshold_breached="partitions_scanned_ratio > 0.5",
            actual_value=1.0,
            telemetry_reference=mock_telemetry_snapshot.snapshot_id
        )
    ]


@pytest.fixture()
def mock_llm_json_response() -> Dict[str, Any]:
    return {
        "root_cause_summary": "The query scanned all partitions due to a missing filter predicate on key column.",
        "confidence": {
            "score": 0.90,
            "reason": "Complete telemetry evidence validates scanning overhead."
        },
        "recommendations": [
            {
                "recommendation_type": "PARTITION_PRUNING",
                "description": "Add filter clause on partitioned date column.",
                "expected_impact": "Will prune scans to single partition.",
                "priority": "HIGH",
                "rationale": "Avoids full scan overhead.",
                "evidence": "Operator 1 TableScan scanned 10/10 partitions."
            }
        ]
    }


# ---------------------------------------------------------------------------
# Test Operator Stats Pruning
# ---------------------------------------------------------------------------

class TestOperatorStatsPruning:
    def test_pruning_returns_empty_when_no_stats(self, mock_detected_issues):
        res = prune_operator_stats(None, mock_detected_issues)
        assert res == []

    def test_prune_operator_stats_extracts_spill_nodes(self, mock_detected_issues):
        operators = [
            {"OPERATOR_ID": 1, "OPERATOR_TYPE": "TableScan", "EXECUTION_TIME_FRACTION": 0.10},
            {"OPERATOR_ID": 2, "OPERATOR_TYPE": "HashJoin", "BYTES_SPILLED_LOCAL": 1024, "EXECUTION_TIME_FRACTION": 0.50},
            {"OPERATOR_ID": 3, "OPERATOR_TYPE": "Aggregate", "BYTES_SPILLED_REMOTE": 500, "EXECUTION_TIME_FRACTION": 0.40}
        ]
        res = prune_operator_stats(operators, mock_detected_issues)
        # Should automatically include nodes with spills
        assert len(res) == 3
        spills = [op for op in res if op.get("BYTES_SPILLED_LOCAL", 0) > 0 or op.get("BYTES_SPILLED_REMOTE", 0) > 0]
        assert len(spills) == 2

    def test_prune_operator_stats_extracts_exploding_nodes(self, mock_detected_issues):
        operators = [
            {
                "OPERATOR_ID": 1, 
                "OPERATOR_TYPE": "Join", 
                "RECORDS_PRODUCED": 500000, 
                "RECORDS_SCANNED": 1000, 
                "EXECUTION_TIME_FRACTION": 0.80
            }
        ]
        res = prune_operator_stats(operators, mock_detected_issues)
        assert len(res) == 1
        assert res[0]["OPERATOR_ID"] == 1

    def test_prune_operator_stats_poor_pruning_table_scans(self, mock_telemetry_snapshot):
        issues = [
            DetectedIssue(
                issue_id=uuid4(),
                type=IssueType.POOR_PARTITION_PRUNING,
                severity=IssueSeverity.HIGH,
                threshold_breached="test",
                actual_value=1.0,
                telemetry_reference=mock_telemetry_snapshot.snapshot_id
            )
        ]
        operators = [
            {
                "OPERATOR_ID": 4, 
                "OPERATOR_TYPE": "TableScan", 
                "PARTITIONS_SCANNED": 8, 
                "PARTITIONS_TOTAL": 10,
                "EXECUTION_TIME_FRACTION": 0.20
            }
        ]
        res = prune_operator_stats(operators, issues)
        assert len(res) == 1
        assert res[0]["OPERATOR_ID"] == 4

    def test_prune_operator_stats_limits_to_max(self, mock_detected_issues):
        # Create 15 operators to trigger the max limits bound
        operators = []
        for i in range(15):
            operators.append({
                "OPERATOR_ID": i,
                "OPERATOR_TYPE": "Aggregate",
                "EXECUTION_TIME_FRACTION": 0.01 * i
            })
        res = prune_operator_stats(operators, mock_detected_issues, max_operators=10)
        assert len(res) == 10
        # Check that top execution fraction operators were preserved
        fractions = [op["EXECUTION_TIME_FRACTION"] for op in res]
        assert min(fractions) >= 0.05


# ---------------------------------------------------------------------------
# Test Prompt Loading
# ---------------------------------------------------------------------------

class TestPromptLoading:
    def test_load_prompt_templates_success(self):
        sys_t, user_t = load_prompt_templates("v1_default")
        assert len(sys_t) > 0
        assert len(user_t) > 0
        assert "{detected_issues}" in user_t

    def test_load_prompt_templates_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_prompt_templates("non_existent_version_xyz")


# ---------------------------------------------------------------------------
# Test Query Performance Analyzer
# ---------------------------------------------------------------------------

class TestQueryPerformanceAnalyzer:
    def test_analyze_finding_success(
        self, mock_settings, mock_telemetry_snapshot, mock_detected_issues, mock_llm_json_response
    ):
        provider = MockLLMProvider(return_value=mock_llm_json_response)
        analyzer = QueryPerformanceAnalyzer(provider, mock_settings)

        res = analyzer.analyze_finding(mock_telemetry_snapshot, mock_detected_issues)
        
        assert isinstance(res, AnalysisResult)
        assert res.root_cause_summary == mock_llm_json_response["root_cause_summary"]
        assert res.confidence.score == 0.90
        assert res.confidence.reason == "Complete telemetry evidence validates scanning overhead."
        assert len(res.recommendations) == 1
        
        rec = res.recommendations[0]
        assert isinstance(rec.recommendation_id, UUID)
        assert rec.recommendation_type == "PARTITION_PRUNING"
        assert rec.description == "Add filter clause on partitioned date column."
        assert rec.expected_impact == "Will prune scans to single partition."
        assert rec.priority == "HIGH"
        assert rec.rationale == "Avoids full scan overhead."
        assert rec.evidence == "Operator 1 TableScan scanned 10/10 partitions."

        # Metadata checks
        assert res.llm_metadata["provider"] == "gemini"
        assert res.llm_metadata["model"] == "gemini-3.5-flash"
        assert res.llm_metadata["prompt_version"] == "v1_default"
        assert res.llm_metadata["success"] is True
        assert res.llm_metadata["validation_failures"] is None

    def test_analyze_finding_raises_on_empty_issues(self, mock_settings, mock_telemetry_snapshot):
        provider = MockLLMProvider()
        analyzer = QueryPerformanceAnalyzer(provider, mock_settings)
        with pytest.raises(ValueError, match="detected issues cannot be empty"):
            analyzer.analyze_finding(mock_telemetry_snapshot, [])

    def test_analyze_finding_transient_retry_success(
        self, mock_settings, mock_telemetry_snapshot, mock_detected_issues, mock_llm_json_response
    ):
        # Provider throws error on first attempt, then succeeds on second attempt
        provider = MockLLMProvider(
            return_value=mock_llm_json_response,
            exception_to_raise=LLMProviderError("Transient rate limit"),
            raise_n_times=1
        )
        
        # Patch time.sleep to avoid slowing down unit tests execution
        with patch("time.sleep"):
            analyzer = QueryPerformanceAnalyzer(provider, mock_settings)
            res = analyzer.analyze_finding(mock_telemetry_snapshot, mock_detected_issues)

        assert provider.call_count == 2
        assert res.llm_metadata["success"] is True

    def test_analyze_finding_transient_retry_exhausted(
        self, mock_settings, mock_telemetry_snapshot, mock_detected_issues
    ):
        # Provider always throws error (exhausting retries limit of 2)
        provider = MockLLMProvider(
            exception_to_raise=LLMProviderError("Permanent rate limit"),
            raise_n_times=5
        )

        with patch("time.sleep"):
            analyzer = QueryPerformanceAnalyzer(provider, mock_settings)
            with pytest.raises(LLMProviderError):
                analyzer.analyze_finding(mock_telemetry_snapshot, mock_detected_issues)
        
        assert provider.call_count == 3  # Initial + 2 retries = 3 calls total

    def test_analyze_finding_validation_retry_and_exhausted(
        self, mock_settings, mock_telemetry_snapshot, mock_detected_issues
    ):
        # Injected response is invalid dict lacking required fields, triggering parsing errors
        invalid_response = {"malformed": "data"}
        provider = MockLLMProvider(return_value=invalid_response)

        with patch("time.sleep"):
            analyzer = QueryPerformanceAnalyzer(provider, mock_settings)
            with pytest.raises(LLMValidationError):
                analyzer.analyze_finding(mock_telemetry_snapshot, mock_detected_issues)

        assert provider.call_count == 3  # Initial + 2 retries
        # Verify validation failure was recorded
        assert len(analyzer.settings.gemini.prompt_version) > 0


# ---------------------------------------------------------------------------
# Test Gemini Provider
# ---------------------------------------------------------------------------

class TestGeminiProvider:
    def test_gemini_provider_requires_api_key(self):
        with pytest.raises(LLMProviderError, match="API key is required"):
            GeminiProvider(api_key="")

    @patch("src.agents.providers.gemini.ChatGoogleGenerativeAI")
    def test_gemini_provider_generate_raw_text(self, mock_chat_class):
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Mocked LLM output narrative text."
        mock_chat.invoke.return_value = mock_response
        mock_chat_class.return_value = mock_chat

        provider = GeminiProvider(api_key="mock-key", model_name="gemini-3.5-flash")
        res = provider.generate(
            system_instruction="System",
            user_prompt="User",
            response_schema=None,
            temperature=0.0
        )
        assert res == "Mocked LLM output narrative text."
        mock_chat_class.assert_called_once_with(
            model="gemini-3.5-flash",
            google_api_key="mock-key",
            temperature=0.0,
            timeout=60.0,
            max_retries=0
        )

    @patch("src.agents.providers.gemini.ChatGoogleGenerativeAI")
    def test_gemini_provider_generate_structured_pydantic(self, mock_chat_class):
        class Schema(BaseModel):
            summary: str

        mock_chat = MagicMock()
        mock_structured = MagicMock()
        
        model_instance = Schema(summary="Mocked structured output summary.")
        mock_structured.invoke.return_value = model_instance
        mock_chat.with_structured_output.return_value = mock_structured
        mock_chat_class.return_value = mock_chat

        provider = GeminiProvider(api_key="mock-key", model_name="gemini-3.5-flash")
        res = provider.generate(
            system_instruction="System",
            user_prompt="User",
            response_schema=Schema,
            temperature=0.0
        )
        assert res == {"summary": "Mocked structured output summary."}

    @patch("src.agents.providers.gemini.ChatGoogleGenerativeAI")
    def test_gemini_provider_timeout_exception(self, mock_chat_class):
        mock_chat = MagicMock()
        mock_chat.invoke.side_effect = Exception("API request timed out on gateway.")
        mock_chat_class.return_value = mock_chat

        provider = GeminiProvider(api_key="mock-key")
        with pytest.raises(LLMTimeoutError):
            provider.generate("Sys", "User")

    @patch("src.agents.providers.gemini.ChatGoogleGenerativeAI")
    def test_gemini_provider_validation_exception(self, mock_chat_class):
        mock_chat = MagicMock()
        mock_chat.invoke.side_effect = Exception("ValidationError occurred in decoding.")
        mock_chat_class.return_value = mock_chat

        provider = GeminiProvider(api_key="mock-key")
        with pytest.raises(LLMValidationError):
            provider.generate("Sys", "User")

    @patch("src.agents.providers.gemini.ChatGoogleGenerativeAI")
    def test_gemini_provider_generic_api_exception(self, mock_chat_class):
        mock_chat = MagicMock()
        mock_chat.invoke.side_effect = Exception("Service unavailable or quota exceeded.")
        mock_chat_class.return_value = mock_chat

        provider = GeminiProvider(api_key="mock-key")
        with pytest.raises(LLMProviderError):
            provider.generate("Sys", "User")
