"""
Tests for POV-4 domain models.

Covers:
    - Valid construction of every domain entity
    - Serialization round-trips (model -> dict -> model)
    - Field validation rules (min_length, ge/le, etc.)
    - Business rule: PerformanceFinding.overall_severity must equal highest issue severity
    - Business rule: confidence_score is rounded to 2dp
    - Optional analysis field (Detection-Only MVP pattern)
    - Frozen model immutability (TelemetrySnapshot, DetectedIssue, etc.)
    - Enum membership and string equivalence (str Enum)
    - AlertEvent mutability (status can be updated post-dispatch)

Target: 100% line coverage of src/domain/models.py and src/domain/enums.py
"""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.domain.enums import AlertDestination, AlertStatus, IssueSeverity, IssueType, EvidenceQuality
from src.domain.models import (
    AlertEvent,
    AnalysisResult,
    ConfidenceScore,
    DetectedIssue,
    PerformanceFinding,
    Recommendation,
    TelemetrySnapshot,
)


# =============================================================================
# Enum tests
# =============================================================================


class TestIssueTypeEnum:
    def test_all_catalog_values_present(self):
        """All 11 issue types from v1_detection_catalog.md must be present."""
        expected = {
            "REMOTE_SPILL", "LOCAL_SPILL", "POOR_PARTITION_PRUNING", "EXPENSIVE_JOIN",
            "CARTESIAN_JOIN", "LONG_RUNNING_QUERY", "QUEUE_OVERLOAD", "PROVISIONING_DELAY",
            "TRANSACTION_BLOCKED", "HIGH_NETWORK_SHUFFLE", "COST_ANOMALY"
        }
        actual = {member.value for member in IssueType}
        assert actual == expected

    def test_is_string_enum(self):
        """IssueType values must be directly usable as strings."""
        assert IssueType.REMOTE_SPILL == "REMOTE_SPILL"

    def test_membership(self):
        assert "REMOTE_SPILL" in [i.value for i in IssueType]

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            IssueType("NOT_A_REAL_ISSUE")


class TestIssueSeverityEnum:
    def test_all_severity_levels_present(self):
        expected = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        actual = {s.value for s in IssueSeverity}
        assert actual == expected

    def test_is_string_enum(self):
        assert IssueSeverity.CRITICAL == "CRITICAL"


class TestAlertDestinationEnum:
    def test_all_destinations_present(self):
        expected = {"TEAMS", "EMAIL", "POV3_WEBHOOK"}
        assert {d.value for d in AlertDestination} == expected


class TestAlertStatusEnum:
    def test_all_statuses_present(self):
        expected = {"PENDING", "SENT", "FAILED"}
        assert {s.value for s in AlertStatus} == expected


# =============================================================================
# TelemetrySnapshot tests
# =============================================================================


class TestTelemetrySnapshot:
    def test_valid_construction(self, valid_telemetry_snapshot):
        snap = TelemetrySnapshot(**valid_telemetry_snapshot)
        assert isinstance(snap.snapshot_id, UUID)
        assert snap.query_id == "01b3c4d5-0000-0001-0000-000200000001"
        assert snap.warehouse_name == "ANALYTICS_WH"

    def test_snapshot_id_auto_generated(self, valid_telemetry_snapshot):
        s1 = TelemetrySnapshot(**valid_telemetry_snapshot)
        s2 = TelemetrySnapshot(**valid_telemetry_snapshot)
        assert s1.snapshot_id != s2.snapshot_id

    def test_operator_stats_defaults_to_none(self, valid_telemetry_snapshot):
        snap = TelemetrySnapshot(**valid_telemetry_snapshot)
        assert snap.operator_stats is None

    def test_operator_stats_accepted_when_provided(self, valid_telemetry_snapshot):
        valid_telemetry_snapshot["operator_stats"] = {"steps": [{"operator": "TableScan"}]}
        snap = TelemetrySnapshot(**valid_telemetry_snapshot)
        assert snap.operator_stats is not None

    def test_empty_query_id_raises(self, valid_telemetry_snapshot):
        valid_telemetry_snapshot["query_id"] = ""
        with pytest.raises(ValidationError, match="query_id"):
            TelemetrySnapshot(**valid_telemetry_snapshot)

    def test_empty_warehouse_name_raises(self, valid_telemetry_snapshot):
        valid_telemetry_snapshot["warehouse_name"] = ""
        with pytest.raises(ValidationError, match="warehouse_name"):
            TelemetrySnapshot(**valid_telemetry_snapshot)

    def test_missing_required_field_raises(self, valid_telemetry_snapshot):
        del valid_telemetry_snapshot["query_history"]
        with pytest.raises(ValidationError, match="query_history"):
            TelemetrySnapshot(**valid_telemetry_snapshot)

    def test_serialization_round_trip(self, valid_telemetry_snapshot):
        snap = TelemetrySnapshot(**valid_telemetry_snapshot)
        data = snap.model_dump()
        restored = TelemetrySnapshot(**data)
        assert restored.snapshot_id == snap.snapshot_id
        assert restored.query_id == snap.query_id

    def test_json_serialization(self, valid_telemetry_snapshot):
        snap = TelemetrySnapshot(**valid_telemetry_snapshot)
        raw = snap.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["query_id"] == snap.query_id
        assert "snapshot_id" in parsed

    def test_frozen_immutability(self, valid_telemetry_snapshot):
        snap = TelemetrySnapshot(**valid_telemetry_snapshot)
        with pytest.raises(Exception):  # ValidationError or TypeError on frozen model
            snap.query_id = "modified"  # type: ignore[misc]


# =============================================================================
# DetectedIssue tests
# =============================================================================


class TestDetectedIssue:
    def test_valid_construction(self, valid_detected_issue):
        issue = DetectedIssue(**valid_detected_issue)
        assert isinstance(issue.issue_id, UUID)
        assert issue.type == IssueType.REMOTE_SPILL
        assert issue.severity == IssueSeverity.HIGH

    def test_issue_id_auto_generated(self, valid_detected_issue):
        i1 = DetectedIssue(**valid_detected_issue)
        i2 = DetectedIssue(**valid_detected_issue)
        assert i1.issue_id != i2.issue_id

    def test_telemetry_reference_is_uuid(self, valid_detected_issue):
        issue = DetectedIssue(**valid_detected_issue)
        assert isinstance(issue.telemetry_reference, UUID)

    def test_invalid_issue_type_raises(self, valid_detected_issue):
        valid_detected_issue["type"] = "FAKE_ISSUE"
        with pytest.raises(ValidationError, match="type"):
            DetectedIssue(**valid_detected_issue)

    def test_invalid_severity_raises(self, valid_detected_issue):
        valid_detected_issue["severity"] = "EXTREME"
        with pytest.raises(ValidationError, match="severity"):
            DetectedIssue(**valid_detected_issue)

    def test_empty_threshold_breached_raises(self, valid_detected_issue):
        valid_detected_issue["threshold_breached"] = ""
        with pytest.raises(ValidationError, match="threshold_breached"):
            DetectedIssue(**valid_detected_issue)

    def test_serialization_round_trip(self, valid_detected_issue):
        issue = DetectedIssue(**valid_detected_issue)
        data = issue.model_dump()
        restored = DetectedIssue(**data)
        assert restored.issue_id == issue.issue_id
        assert restored.type == issue.type

    def test_frozen_immutability(self, valid_detected_issue):
        issue = DetectedIssue(**valid_detected_issue)
        with pytest.raises(Exception):
            issue.severity = IssueSeverity.LOW  # type: ignore[misc]


# =============================================================================
# Recommendation tests
# =============================================================================


class TestRecommendation:
    def test_valid_construction(self, valid_recommendation):
        rec = Recommendation(**valid_recommendation)
        assert isinstance(rec.recommendation_id, UUID)
        assert rec.recommendation_type == "QUERY"
        assert rec.priority == "HIGH"
        assert rec.rationale == "Pushing down filters reduces the row count entering the aggregate and join operators, avoiding memory thrashing."
        assert rec.evidence == "Operator 3 (HashJoin) spilled 2GB to remote storage and accounted for 85% of execution time."

    def test_recommendation_id_auto_generated(self, valid_recommendation):
        r1 = Recommendation(**valid_recommendation)
        r2 = Recommendation(**valid_recommendation)
        assert r1.recommendation_id != r2.recommendation_id

    def test_empty_recommendation_type_raises(self, valid_recommendation):
        valid_recommendation["recommendation_type"] = ""
        with pytest.raises(ValidationError, match="recommendation_type"):
            Recommendation(**valid_recommendation)

    def test_empty_description_raises(self, valid_recommendation):
        valid_recommendation["description"] = ""
        with pytest.raises(ValidationError, match="description"):
            Recommendation(**valid_recommendation)

    def test_empty_expected_impact_raises(self, valid_recommendation):
        valid_recommendation["expected_impact"] = ""
        with pytest.raises(ValidationError, match="expected_impact"):
            Recommendation(**valid_recommendation)

    def test_empty_priority_raises(self, valid_recommendation):
        valid_recommendation["priority"] = ""
        with pytest.raises(ValidationError, match="priority"):
            Recommendation(**valid_recommendation)

    def test_empty_rationale_raises(self, valid_recommendation):
        valid_recommendation["rationale"] = ""
        with pytest.raises(ValidationError, match="rationale"):
            Recommendation(**valid_recommendation)

    def test_empty_evidence_raises(self, valid_recommendation):
        valid_recommendation["evidence"] = ""
        with pytest.raises(ValidationError, match="evidence"):
            Recommendation(**valid_recommendation)

    def test_recommendation_type_is_extensible_string(self, valid_recommendation):
        """recommendation_type must accept any non-empty string (not an enum)."""
        valid_recommendation["recommendation_type"] = "SOME_FUTURE_TYPE_V2"
        rec = Recommendation(**valid_recommendation)
        assert rec.recommendation_type == "SOME_FUTURE_TYPE_V2"

    def test_serialization_round_trip(self, valid_recommendation):
        rec = Recommendation(**valid_recommendation)
        data = rec.model_dump()
        restored = Recommendation(**data)
        assert restored.recommendation_id == rec.recommendation_id


# =============================================================================
# AnalysisResult tests
# =============================================================================


class TestAnalysisResult:
    def test_valid_construction(self, valid_analysis_result):
        result = AnalysisResult(**valid_analysis_result)
        assert isinstance(result.analysis_id, UUID)
        assert len(result.recommendations) == 1

    def test_analysis_id_auto_generated(self, valid_analysis_result):
        a1 = AnalysisResult(**valid_analysis_result)
        a2 = AnalysisResult(**valid_analysis_result)
        assert a1.analysis_id != a2.analysis_id

    def test_empty_root_cause_summary_raises(self, valid_analysis_result):
        valid_analysis_result["root_cause_summary"] = ""
        with pytest.raises(ValidationError, match="root_cause_summary"):
            AnalysisResult(**valid_analysis_result)

    def test_empty_recommendations_list_raises(self, valid_analysis_result):
        valid_analysis_result["recommendations"] = []
        with pytest.raises(ValidationError, match="recommendations"):
            AnalysisResult(**valid_analysis_result)

    def test_confidence_score_on_analysis_result(self, valid_analysis_result):
        """
        Confidence score must be on AnalysisResult.
        """
        result = AnalysisResult(**valid_analysis_result)
        assert hasattr(result, "confidence")
        assert result.confidence.score == 0.82
        assert isinstance(result.confidence, ConfidenceScore)

    def test_llm_metadata_is_dict(self, valid_analysis_result):
        result = AnalysisResult(**valid_analysis_result)
        assert isinstance(result.llm_metadata, dict)

    def test_serialization_round_trip(self, valid_analysis_result):
        result = AnalysisResult(**valid_analysis_result)
        data = result.model_dump()
        restored = AnalysisResult(**data)
        assert restored.analysis_id == result.analysis_id


# =============================================================================
# ConfidenceScore tests
# =============================================================================


class TestConfidenceScore:
    def test_confidence_score_rounded_to_2dp(self):
        c = ConfidenceScore(score=0.79999, reason="test")
        assert c.score == 0.80

    def test_confidence_score_below_zero_raises(self):
        with pytest.raises(ValidationError, match="score"):
            ConfidenceScore(score=-0.1, reason="test")

    def test_confidence_score_above_one_raises(self):
        with pytest.raises(ValidationError, match="score"):
            ConfidenceScore(score=1.01, reason="test")


# =============================================================================
# PerformanceFinding tests
# =============================================================================


class TestPerformanceFinding:
    def test_valid_construction_with_analysis(self, valid_performance_finding):
        finding = PerformanceFinding(**valid_performance_finding)
        assert isinstance(finding.finding_id, UUID)
        assert finding.overall_severity == IssueSeverity.HIGH
        assert finding.analysis is not None

    def test_valid_construction_without_analysis(self, valid_performance_finding):
        """Detection-Only MVP: analysis=None must be valid."""
        valid_performance_finding["analysis"] = None
        finding = PerformanceFinding(**valid_performance_finding)
        assert finding.analysis is None

    def test_finding_id_auto_generated(self, valid_performance_finding):
        f1 = PerformanceFinding(**valid_performance_finding)
        f2 = PerformanceFinding(**valid_performance_finding)
        assert f1.finding_id != f2.finding_id

    def test_evidence_quality_on_finding(self, valid_performance_finding):
        """Evidence quality must live on PerformanceFinding."""
        finding = PerformanceFinding(**valid_performance_finding)
        assert hasattr(finding, "evidence_quality")
        assert finding.evidence_quality == EvidenceQuality.COMPLETE

    def test_overall_severity_must_match_highest_issue(self, valid_performance_finding):
        """
        Business rule: overall_severity must equal the highest DetectedIssue severity.
        Reference: docs/detection-framework.md §3
        """
        valid_performance_finding["overall_severity"] = IssueSeverity.LOW  # Incorrect: issue is HIGH
        with pytest.raises(ValidationError, match="overall_severity"):
            PerformanceFinding(**valid_performance_finding)

    def test_empty_issues_list_raises(self, valid_performance_finding):
        valid_performance_finding["issues"] = []
        with pytest.raises(ValidationError, match="issues"):
            PerformanceFinding(**valid_performance_finding)

    def test_metrics_is_telemetry_snapshot(self, valid_performance_finding):
        finding = PerformanceFinding(**valid_performance_finding)
        assert isinstance(finding.metrics, TelemetrySnapshot)

    def test_serialization_round_trip(self, valid_performance_finding):
        finding = PerformanceFinding(**valid_performance_finding)
        data = finding.model_dump()
        restored = PerformanceFinding(**data)
        assert restored.finding_id == finding.finding_id
        assert restored.overall_severity == finding.overall_severity

    def test_json_serialization(self, valid_performance_finding):
        finding = PerformanceFinding(**valid_performance_finding)
        raw = finding.model_dump_json()
        parsed = json.loads(raw)
        assert "finding_id" in parsed
        assert parsed["overall_severity"] == "HIGH"
        assert parsed["evidence_quality"] == "COMPLETE"

    def test_frozen_immutability(self, valid_performance_finding):
        finding = PerformanceFinding(**valid_performance_finding)
        with pytest.raises(Exception):
            finding.overall_severity = IssueSeverity.LOW  # type: ignore[misc]


# =============================================================================
# AlertEvent tests
# =============================================================================


class TestAlertEvent:
    def test_valid_construction(self):
        finding_id = uuid4()
        event = AlertEvent(
            finding_reference=finding_id,
            destination=AlertDestination.TEAMS,
        )
        assert isinstance(event.alert_id, UUID)
        assert event.status == AlertStatus.PENDING
        assert event.delivery_timestamp is None

    def test_alert_id_auto_generated(self):
        finding_id = uuid4()
        e1 = AlertEvent(finding_reference=finding_id, destination=AlertDestination.EMAIL)
        e2 = AlertEvent(finding_reference=finding_id, destination=AlertDestination.EMAIL)
        assert e1.alert_id != e2.alert_id

    def test_status_defaults_to_pending(self):
        event = AlertEvent(finding_reference=uuid4(), destination=AlertDestination.POV3_WEBHOOK)
        assert event.status == AlertStatus.PENDING

    def test_status_is_mutable(self):
        """AlertEvent must be mutable — status is updated post-dispatch."""
        event = AlertEvent(finding_reference=uuid4(), destination=AlertDestination.TEAMS)
        event.status = AlertStatus.SENT
        assert event.status == AlertStatus.SENT

    def test_delivery_timestamp_is_mutable(self):
        event = AlertEvent(finding_reference=uuid4(), destination=AlertDestination.EMAIL)
        now = datetime.now(tz=timezone.utc)
        event.delivery_timestamp = now
        assert event.delivery_timestamp == now

    def test_invalid_destination_raises(self):
        with pytest.raises(ValidationError, match="destination"):
            AlertEvent(finding_reference=uuid4(), destination="SLACK")  # type: ignore[arg-type]

    def test_serialization_round_trip(self):
        finding_id = uuid4()
        event = AlertEvent(
            finding_reference=finding_id,
            destination=AlertDestination.POV3_WEBHOOK,
            status=AlertStatus.FAILED,
        )
        data = event.model_dump()
        restored = AlertEvent(**data)
        assert restored.alert_id == event.alert_id
        assert restored.status == AlertStatus.FAILED
