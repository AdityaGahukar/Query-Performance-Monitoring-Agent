from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.domain.enums import AlertDestination, AlertStatus, IssueSeverity, EvidenceQuality
from src.domain.models import AlertEvent, AnalysisResult, DetectedIssue, PerformanceFinding, TelemetrySnapshot
from src.storage.repository import SnowflakeRepository


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock()


def test_save_finding_calls_merge(mock_client, valid_performance_finding):
    repo = SnowflakeRepository(mock_client)
    finding = PerformanceFinding(**valid_performance_finding)

    repo.save_finding(finding)

    # Verify connection executed the merge query
    mock_client.execute_query.assert_called_once()
    args, kwargs = mock_client.execute_query.call_args
    query_str = args[0]
    params = args[1]

    # Verify query contains key keywords
    assert "MERGE INTO" in query_str
    assert "FINDING_ID" in query_str

    # Verify parameters match serialized fields
    assert params[0] == str(finding.finding_id)
    assert params[2] == finding.query_id
    assert params[3] == finding.warehouse
    assert params[4] == finding.overall_severity.value
    assert params[5] == finding.evidence_quality.value
    # issues must be a valid JSON list string
    assert "REMOTE_SPILL" in params[6]


def test_get_finding_reconstructs_model(mock_client, valid_performance_finding):
    repo = SnowflakeRepository(mock_client)
    finding = PerformanceFinding(**valid_performance_finding)

    # Mock the fetch_one database call to return serialized database row values
    import json
    issues_json = json.dumps([issue.model_dump() for issue in finding.issues], default=str)
    metrics_json = finding.metrics.model_dump_json()
    analysis_json = finding.analysis.model_dump_json() if finding.analysis else None

    mock_client.fetch_one.return_value = {
        "FINDING_ID": str(finding.finding_id),
        "TIMESTAMP": finding.timestamp,
        "QUERY_ID": finding.query_id,
        "WAREHOUSE": finding.warehouse,
        "OVERALL_SEVERITY": finding.overall_severity.value,
        "EVIDENCE_QUALITY": finding.evidence_quality.value,
        "ISSUES": issues_json,
        "METRICS": metrics_json,
        "ANALYSIS": analysis_json,
    }

    retrieved = repo.get_finding(finding.finding_id)

    assert retrieved is not None
    assert retrieved.finding_id == finding.finding_id
    assert retrieved.query_id == finding.query_id
    assert retrieved.overall_severity == finding.overall_severity
    assert retrieved.evidence_quality == finding.evidence_quality
    assert len(retrieved.issues) == 1
    assert retrieved.issues[0].type == finding.issues[0].type
    assert retrieved.analysis is not None
    assert retrieved.analysis.analysis_id == finding.analysis.analysis_id


def test_save_alert_event_calls_merge(mock_client):
    repo = SnowflakeRepository(mock_client)
    event = AlertEvent(
        alert_id=uuid4(),
        finding_reference=uuid4(),
        destination=AlertDestination.TEAMS,
        status=AlertStatus.PENDING,
    )

    repo.save_alert_event(event)

    mock_client.execute_query.assert_called_once()
    args, _ = mock_client.execute_query.call_args
    assert "MERGE INTO" in args[0]
    assert "ALERT_ID" in args[0]
    assert args[1][0] == str(event.alert_id)
    assert args[1][3] == "PENDING"


def test_get_alert_event_reconstructs_model(mock_client):
    repo = SnowflakeRepository(mock_client)
    alert_id = uuid4()
    finding_ref = uuid4()
    now = datetime.now(timezone.utc)

    mock_client.fetch_one.return_value = {
        "ALERT_ID": str(alert_id),
        "FINDING_REFERENCE": str(finding_ref),
        "DESTINATION": "TEAMS",
        "STATUS": "SENT",
        "DELIVERY_TIMESTAMP": now,
    }

    retrieved = repo.get_alert_event(alert_id)

    assert retrieved is not None
    assert retrieved.alert_id == alert_id
    assert retrieved.finding_reference == finding_ref
    assert retrieved.destination == AlertDestination.TEAMS
    assert retrieved.status == AlertStatus.SENT
    assert retrieved.delivery_timestamp == now


def test_initialize_schema_success(mock_client):
    from unittest.mock import mock_open, patch
    repo = SnowflakeRepository(mock_client)
    mock_sql = "CREATE TABLE IF NOT EXISTS FOO;\nCREATE TABLE IF NOT EXISTS BAR;"
    
    with patch("builtins.open", mock_open(read_data=mock_sql)):
        repo.initialize_schema()
        
    assert mock_client.execute_query.call_count == 2
    mock_client.execute_query.assert_any_call("CREATE TABLE IF NOT EXISTS FOO")
    mock_client.execute_query.assert_any_call("CREATE TABLE IF NOT EXISTS BAR")


def test_initialize_schema_failure(mock_client):
    from unittest.mock import patch
    repo = SnowflakeRepository(mock_client)
    with patch("builtins.open", side_effect=FileNotFoundError("ddl.sql not found")):
        with pytest.raises(FileNotFoundError):
            repo.initialize_schema()


def test_get_finding_not_found(mock_client):
    repo = SnowflakeRepository(mock_client)
    mock_client.fetch_one.return_value = None
    assert repo.get_finding(uuid4()) is None


def test_get_alert_event_not_found(mock_client):
    repo = SnowflakeRepository(mock_client)
    mock_client.fetch_one.return_value = None
    assert repo.get_alert_event(uuid4()) is None


def test_get_finding_naive_timestamp(mock_client, valid_performance_finding):
    repo = SnowflakeRepository(mock_client)
    finding = PerformanceFinding(**valid_performance_finding)
    import json
    issues_json = json.dumps([issue.model_dump() for issue in finding.issues], default=str)
    metrics_json = finding.metrics.model_dump_json()
    analysis_json = finding.analysis.model_dump_json() if finding.analysis else None

    naive_dt = datetime.now()
    mock_client.fetch_one.return_value = {
        "FINDING_ID": str(finding.finding_id),
        "TIMESTAMP": naive_dt,
        "QUERY_ID": finding.query_id,
        "WAREHOUSE": finding.warehouse,
        "OVERALL_SEVERITY": finding.overall_severity.value,
        "EVIDENCE_QUALITY": finding.evidence_quality.value,
        "ISSUES": issues_json,
        "METRICS": metrics_json,
        "ANALYSIS": analysis_json,
    }

    retrieved = repo.get_finding(finding.finding_id)
    assert retrieved.timestamp.tzinfo == timezone.utc


def test_get_alert_event_naive_timestamp(mock_client):
    repo = SnowflakeRepository(mock_client)
    alert_id = uuid4()
    finding_ref = uuid4()
    naive_dt = datetime.now()

    mock_client.fetch_one.return_value = {
        "ALERT_ID": str(alert_id),
        "FINDING_REFERENCE": str(finding_ref),
        "DESTINATION": "TEAMS",
        "STATUS": "SENT",
        "DELIVERY_TIMESTAMP": naive_dt,
    }

    retrieved = repo.get_alert_event(alert_id)
    assert retrieved.delivery_timestamp.tzinfo == timezone.utc
