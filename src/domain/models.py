"""
POV-4: Core domain models.

These Pydantic V2 models are the absolute source of truth for all data structures
in POV-4. Every component — collection, detection, analysis, persistence, and
notification — operates on these entities.

Design authority: docs/domain-model/domain_model.md
Do not add fields not approved in that document.

Assumption: The `analysis` field on PerformanceFinding is Optional to support
the Detection-Only MVP milestone (Phase 4 complete, Phase 5 not yet integrated).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


from src.domain.enums import AlertDestination, AlertStatus, IssueSeverity, IssueType


# ---------------------------------------------------------------------------
# TelemetrySnapshot
# ---------------------------------------------------------------------------


class TelemetrySnapshot(BaseModel):
    """
    A point-in-time capture of Snowflake workload metrics.

    Constructed by the Data Collection Layer from five V1 telemetry sources:
        - QUERY_HISTORY        -> query_history
        - QUERY_PROFILE        -> query_profile  (optional, fetched on-demand)
        - WAREHOUSE_LOAD_HISTORY -> warehouse_load
        - METERING_HISTORY     -> metering_context
        - QUERY_ATTRIBUTION_HISTORY -> query_attribution

    Reference: docs/domain-model/domain_model.md §1
    Reference: docs/collection-strategy.md §1
    """

    snapshot_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this telemetry snapshot.",
    )
    timestamp: datetime = Field(
        description="UTC timestamp when this snapshot was captured.",
    )
    query_id: str = Field(
        description="Snowflake QUERY_ID that this snapshot relates to.",
        min_length=1,
    )
    warehouse_name: str = Field(
        description="Name of the Snowflake warehouse that executed the query.",
        min_length=1,
    )
    query_history: dict[str, Any] = Field(
        description=(
            "Raw execution statistics from QUERY_HISTORY: spills, queue times, "
            "execution duration, partition scan ratios, etc."
        ),
    )
    query_profile: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Execution plan tree from QUERY_PROFILE. "
            "Fetched on-demand only for queries flagged by the Detection Engine. "
            "Null when the profile was not retrieved or retrieval failed."
        ),
    )
    warehouse_load: dict[str, Any] = Field(
        description=(
            "System-level concurrency context from WAREHOUSE_LOAD_HISTORY "
            "captured during the query execution window."
        ),
    )
    metering_context: dict[str, Any] = Field(
        description=(
            "Account or warehouse credit consumption from METERING_HISTORY "
            "for the relevant time window."
        ),
    )
    query_attribution: dict[str, Any] = Field(
        description=(
            "Exact compute cost attributed to this specific query "
            "from QUERY_ATTRIBUTION_HISTORY."
        ),
    )

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# DetectedIssue
# ---------------------------------------------------------------------------


class DetectedIssue(BaseModel):
    """
    A specific performance bottleneck identified by the deterministic rule engine.

    Produced exclusively by the Issue Detection Engine (src/services/detector.py).
    Never created by the LLM or any other component.

    Reference: docs/domain-model/domain_model.md §2
    Reference: docs/detection-framework.md §1–§4
    """

    issue_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this detected issue.",
    )
    type: IssueType = Field(
        description="Category of performance issue as defined in the issue catalog.",
    )
    severity: IssueSeverity = Field(
        description=(
            "Deterministically computed severity based on threshold breach magnitude. "
            "See docs/detection-framework.md §3 for severity rules."
        ),
    )
    threshold_breached: str = Field(
        description=(
            "Human-readable description of the threshold that was breached, "
            "e.g. 'bytes_spilled_to_remote_storage > 1073741824'."
        ),
        min_length=1,
    )
    actual_value: float = Field(
        description="The raw metric value that breached the threshold.",
    )
    telemetry_reference: UUID = Field(
        description="Foreign key reference to the TelemetrySnapshot that produced this issue.",
    )

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


class Recommendation(BaseModel):
    """
    A single actionable optimization step generated by the LLM Analysis Agent.

    The `recommendation_type` field is intentionally a plain string (not an Enum)
    to remain extensible as new recommendation categories emerge without requiring
    model code changes.

    Reference: docs/domain-model/domain_model.md §3
    """

    recommendation_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this recommendation.",
    )
    recommendation_type: str = Field(
        description=(
            "Extensible category label for this recommendation, "
            "e.g. 'SCALE_UP', 'REWRITE_SQL', 'CLUSTER_TABLE', 'ENABLE_RESULT_CACHE'."
        ),
        min_length=1,
    )
    description: str = Field(
        description="Full human-readable description of the recommended action.",
        min_length=1,
    )
    expected_impact: str = Field(
        description=(
            "LLM-generated statement of the expected performance or cost impact "
            "if this recommendation is applied."
        ),
        min_length=1,
    )

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# AnalysisResult
# ---------------------------------------------------------------------------


class AnalysisResult(BaseModel):
    """
    The structured output from the single LLM Analysis Agent (Google Gemini).

    Produced by src/agents/analyzer.py via LangChain's PydanticOutputParser.
    If the LLM fails or times out, the pipeline proceeds with analysis=None
    on the PerformanceFinding and applies a confidence score penalty.

    Note: confidence_score and confidence_reason are NOT part of AnalysisResult.
    They live on PerformanceFinding because confidence is computed deterministically
    by the framework, not by the LLM.

    Reference: docs/domain-model/domain_model.md §4
    Reference: docs/adr/0002-single-agent-architecture.md
    """

    analysis_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this analysis result.",
    )
    root_cause_summary: str = Field(
        description="LLM-generated root cause analysis narrative.",
        min_length=1,
    )
    recommendations: list[Recommendation] = Field(
        description="Ordered list of actionable recommendations from the LLM.",
        min_length=1,
    )
    llm_metadata: dict[str, Any] = Field(
        description=(
            "Operational metadata from the LLM invocation: "
            "model version, latency_ms, input_tokens, output_tokens."
        ),
    )

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# PerformanceFinding
# ---------------------------------------------------------------------------


class PerformanceFinding(BaseModel):
    """
    The aggregate persisted record that serves as POV-4's source of truth.

    Lifecycle:
        1. Created with analysis=None after Detection Engine runs (Detection-Only MVP).
        2. Updated with an AnalysisResult after the LLM agent completes.
        3. Dispatched as an AlertEvent payload to Teams, Email, and POV-3.

    Severity rule: overall_severity is the highest severity across all issues.
    Confidence rule: starts at 1.0 and is penalised deterministically.
        See docs/detection-framework.md §4 for penalty rules.

    Reference: docs/domain-model/domain_model.md §5
    Reference: docs/hld/high_level_design.md §3
    """

    finding_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this performance finding.",
    )
    timestamp: datetime = Field(
        description="UTC timestamp when this finding was created.",
    )
    query_id: str = Field(
        description="Snowflake QUERY_ID that triggered this finding.",
        min_length=1,
    )
    warehouse: str = Field(
        description="Name of the Snowflake warehouse associated with this finding.",
        min_length=1,
    )
    overall_severity: IssueSeverity = Field(
        description=(
            "Highest severity across all detected issues in this finding. "
            "Computed deterministically by the Detection Engine."
        ),
    )
    confidence_score: float = Field(
        description=(
            "Structural completeness score for this finding, range [0.0, 1.0]. "
            "Starts at 1.0 and is reduced by deterministic penalties "
            "(e.g. missing query profile, LLM fallback). "
            "See docs/detection-framework.md §4."
        ),
        ge=0.0,
        le=1.0,
    )
    confidence_reason: str = Field(
        description=(
            "Human-readable explanation of confidence score deductions applied, "
            "e.g. '1.0 - 0.2 (query profile unavailable)'."
        ),
        min_length=1,
    )
    issues: list[DetectedIssue] = Field(
        description="One or more performance issues detected in this finding.",
        min_length=1,
    )
    metrics: TelemetrySnapshot = Field(
        description="The telemetry snapshot that was evaluated to produce this finding.",
    )
    analysis: AnalysisResult | None = Field(
        default=None,
        description=(
            "LLM-generated root cause analysis. "
            "None when the Detection-Only MVP stage is active or LLM is unavailable."
        ),
    )

    @field_validator("confidence_score")
    @classmethod
    def validate_confidence_score(cls, v: float) -> float:
        """Ensures confidence score is rounded to 2 decimal places for consistency."""
        return round(v, 2)

    @model_validator(mode="after")
    def validate_overall_severity(self) -> PerformanceFinding:
        """
        Validates that overall_severity matches the highest severity across issues.

        This enforces the detection framework rule:
            'PerformanceFinding severity inherits the highest DetectedIssue severity.'
        """
        severity_order = [
            IssueSeverity.LOW,
            IssueSeverity.MEDIUM,
            IssueSeverity.HIGH,
            IssueSeverity.CRITICAL,
        ]
        # Note: `min_length=1` on the `issues` field guarantees a non-empty list
        # before this validator runs. No early-exit guard is needed.
        highest = max(self.issues, key=lambda i: severity_order.index(i.severity)).severity
        if self.overall_severity != highest:
            raise ValueError(
                f"overall_severity '{self.overall_severity}' does not match "
                f"the highest issue severity '{highest}'. "
                "PerformanceFinding.overall_severity must equal the highest DetectedIssue.severity."
            )
        return self

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# AlertEvent
# ---------------------------------------------------------------------------


class AlertEvent(BaseModel):
    """
    Represents a single notification dispatch attempt for a PerformanceFinding.

    One PerformanceFinding may produce multiple AlertEvents (one per destination).
    Failed events (status=FAILED) are stored in the DLQ and retried by the
    APScheduler sweeper cron job.

    Reference: docs/domain-model/domain_model.md §6
    Reference: docs/lld/low_level_design.md §5.3
    """

    alert_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this alert dispatch event.",
    )
    finding_reference: UUID = Field(
        description="Foreign key reference to the PerformanceFinding that triggered this alert.",
    )
    destination: AlertDestination = Field(
        description="Target delivery channel for this alert.",
    )
    status: AlertStatus = Field(
        default=AlertStatus.PENDING,
        description="Current lifecycle state of this alert delivery attempt.",
    )
    delivery_timestamp: datetime | None = Field(
        default=None,
        description=(
            "UTC timestamp of successful or failed delivery attempt. "
            "None while status is PENDING."
        ),
    )

    model_config = {"frozen": False}  # Mutable: status and delivery_timestamp are updated post-dispatch.
