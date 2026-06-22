"""
Shared pytest fixtures for POV-4 Phase 1 tests.

Provides valid, minimal factory functions for all domain entities.
These fixtures are the canonical test data for Phase 1 and will be
extended (not replaced) in future phases.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.enums import AlertDestination, AlertStatus, IssueSeverity, IssueType, EvidenceQuality


# ---------------------------------------------------------------------------
# Primitive test data factories
# ---------------------------------------------------------------------------


def make_snapshot_id() -> str:
    return str(uuid4())


def make_utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Raw dict payloads (as they would arrive from Snowflake)
# ---------------------------------------------------------------------------


@pytest.fixture()
def valid_query_history() -> dict:
    """Minimal QUERY_HISTORY payload as returned by the collector."""
    return {
        "execution_time_ms": 45000,
        "queued_overload_time_ms": 12000,
        "bytes_spilled_to_local_storage": 0,
        "bytes_spilled_to_remote_storage": 2_000_000_000,  # 2 GB remote spill
        "partitions_scanned": 980,
        "partitions_total": 1000,
        "error_code": None,
    }


@pytest.fixture()
def valid_warehouse_load() -> dict:
    """Minimal WAREHOUSE_LOAD_HISTORY payload."""
    return {
        "avg_running": 7.8,
        "avg_queued_load": 3.2,
        "avg_queued_provisioning": 0.0,
    }


@pytest.fixture()
def valid_metering_context() -> dict:
    """Minimal METERING_HISTORY payload."""
    return {
        "credits_used_compute": 14.5,
        "start_time": "2026-06-19T06:00:00Z",
        "end_time": "2026-06-19T07:00:00Z",
    }


@pytest.fixture()
def valid_query_attribution() -> dict:
    """Minimal QUERY_ATTRIBUTION_HISTORY payload."""
    return {
        "credits_attributed": 0.87,
    }


# ---------------------------------------------------------------------------
# Domain entity fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def snapshot_id() -> str:
    return str(uuid4())


@pytest.fixture()
def valid_telemetry_snapshot(
    valid_query_history,
    valid_warehouse_load,
    valid_metering_context,
    valid_query_attribution,
) -> dict:
    """Complete, valid TelemetrySnapshot constructor kwargs."""
    return {
        "timestamp": make_utc_now(),
        "query_id": "01b3c4d5-0000-0001-0000-000200000001",
        "warehouse_name": "ANALYTICS_WH",
        "query_history": valid_query_history,
        "query_profile": None,  # Not fetched yet — on-demand only
        "warehouse_load": valid_warehouse_load,
        "metering_context": valid_metering_context,
        "query_attribution": valid_query_attribution,
    }


@pytest.fixture()
def valid_detected_issue(valid_telemetry_snapshot) -> dict:
    """Valid DetectedIssue constructor kwargs for a REMOTE_SPILL."""
    from src.domain.models import TelemetrySnapshot

    snapshot = TelemetrySnapshot(**valid_telemetry_snapshot)
    return {
        "type": IssueType.REMOTE_SPILL,
        "severity": IssueSeverity.HIGH,
        "threshold_breached": "bytes_spilled_to_remote_storage > 1073741824",
        "actual_value": 2_000_000_000.0,
        "telemetry_reference": snapshot.snapshot_id,
    }


@pytest.fixture()
def valid_recommendation() -> dict:
    """Valid Recommendation constructor kwargs."""
    return {
        "recommendation_type": "REWRITE_SQL",
        "description": "Reduce the result set size before the JOIN by pushing filters earlier.",
        "expected_impact": "Estimated 60-80% reduction in remote spill volume.",
    }


@pytest.fixture()
def valid_analysis_result(valid_recommendation) -> dict:
    """Valid AnalysisResult constructor kwargs."""
    from src.domain.models import Recommendation

    return {
        "root_cause_summary": (
            "The query performs a large Cartesian JOIN before applying filters, "
            "causing memory exhaustion and forcing data to remote storage."
        ),
        "recommendations": [Recommendation(**valid_recommendation)],
        "llm_metadata": {
            "model": "gemini-1.5-pro",
            "latency_ms": 1823,
            "input_tokens": 412,
            "output_tokens": 187,
        },
        "confidence": {
            "score": 0.82,
            "reason": "Operator statistics, query history, and warehouse telemetry consistently indicate memory pressure caused by a large join."
        },
    }


@pytest.fixture()
def valid_performance_finding(
    valid_telemetry_snapshot,
    valid_detected_issue,
    valid_analysis_result,
) -> dict:
    """Valid PerformanceFinding constructor kwargs (with analysis)."""
    from src.domain.models import AnalysisResult, DetectedIssue, TelemetrySnapshot

    snapshot = TelemetrySnapshot(**valid_telemetry_snapshot)
    issue = DetectedIssue(**valid_detected_issue)
    analysis = AnalysisResult(**valid_analysis_result)

    return {
        "timestamp": make_utc_now(),
        "query_id": snapshot.query_id,
        "warehouse": snapshot.warehouse_name,
        "overall_severity": IssueSeverity.HIGH,
        "evidence_quality": EvidenceQuality.COMPLETE,
        "issues": [issue],
        "metrics": snapshot,
        "analysis": analysis,
    }

