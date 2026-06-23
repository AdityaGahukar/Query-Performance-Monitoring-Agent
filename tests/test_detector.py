from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.domain.enums import EvidenceQuality, IssueSeverity, IssueType
from src.domain.models import TelemetrySnapshot
from src.services.detector import IssueDetector


@pytest.fixture
def base_snapshot() -> TelemetrySnapshot:
    """Provides a baseline, complete TelemetrySnapshot where no rules trigger."""
    return TelemetrySnapshot(
        snapshot_id=uuid4(),
        timestamp=datetime.now(timezone.utc),
        query_id="TEST_QID",
        warehouse_name="COMPUTE_WH",
        query_history={
            "QUERY_ID": "TEST_QID",
            "WAREHOUSE_NAME": "COMPUTE_WH",
            "START_TIME": datetime.now(timezone.utc),
            "END_TIME": datetime.now(timezone.utc),
            "EXECUTION_TIME": 100,
            "QUEUED_OVERLOAD_TIME": 0,
            "QUEUED_PROVISIONING_TIME": 0,
            "BYTES_SPILLED_TO_LOCAL_STORAGE": 0,
            "BYTES_SPILLED_TO_REMOTE_STORAGE": 0,
            "PARTITIONS_SCANNED": 0,
            "PARTITIONS_TOTAL": 0,
            "ROWS_PRODUCED": 10,
            "BYTES_SCANNED": 1000,
            "QUERY_TYPE": "SELECT",
            "TRANSACTION_BLOCKED_TIME": 0,
            "WAREHOUSE_SIZE": "X-Small",
        },
        warehouse_load={
            "CLUSTER_COUNT": 1,
            "MAX_CLUSTER_COUNT": 1,
        },
        metering_context={
            "CREDITS_USED_COMPUTE": 0.0,
        },
        query_attribution={
            "CREDITS_ATTRIBUTED_COMPUTE": 0.0,
        },
    )


def test_no_issues_trigger_normally(base_snapshot):
    detector = IssueDetector()
    issues, quality = detector.evaluate_all(base_snapshot)
    assert len(issues) == 0
    assert quality == EvidenceQuality.COMPLETE


def test_remote_spill_rule(base_snapshot):
    detector = IssueDetector()

    # Under threshold (0 bytes spilled)
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 0

    # Medium Severity: 1 byte spilled
    base_snapshot.query_history["BYTES_SPILLED_TO_REMOTE_STORAGE"] = 1
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 1
    assert issues[0].type == IssueType.REMOTE_SPILL
    assert issues[0].severity == IssueSeverity.MEDIUM

    # High Severity: 11 GB spilled
    base_snapshot.query_history["BYTES_SPILLED_TO_REMOTE_STORAGE"] = 11_000_000_000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert issues[0].severity == IssueSeverity.HIGH

    # Critical Severity: 55 GB spilled
    base_snapshot.query_history["BYTES_SPILLED_TO_REMOTE_STORAGE"] = 55_000_000_000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert issues[0].severity == IssueSeverity.CRITICAL


def test_local_spill_rule(base_snapshot):
    detector = IssueDetector()
    base_snapshot.query_history["WAREHOUSE_SIZE"] = "X-Small"  # 16 GB RAM = 17,179,869,184 bytes

    # Below floor threshold (4 GB spilled, ratio is 0.25) -> no trigger
    base_snapshot.query_history["BYTES_SPILLED_TO_LOCAL_STORAGE"] = 4_000_000_000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 0

    # Below ratio threshold but above floor (6 GB spilled, ratio 6/16 = 0.375) -> no trigger
    base_snapshot.query_history["BYTES_SPILLED_TO_LOCAL_STORAGE"] = 6_000_000_000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 0

    # Low Severity: 10 GB spilled (ratio 10/16 = 0.625)
    base_snapshot.query_history["BYTES_SPILLED_TO_LOCAL_STORAGE"] = 10_000_000_000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 1
    assert issues[0].type == IssueType.LOCAL_SPILL
    assert issues[0].severity == IssueSeverity.LOW

    # Medium Severity: 18 GB spilled (ratio 18/16 = 1.125)
    base_snapshot.query_history["BYTES_SPILLED_TO_LOCAL_STORAGE"] = 18_000_000_000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert issues[0].severity == IssueSeverity.MEDIUM

    # High Severity: 35 GB spilled (ratio 35/16 = 2.1875)
    base_snapshot.query_history["BYTES_SPILLED_TO_LOCAL_STORAGE"] = 35_000_000_000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert issues[0].severity == IssueSeverity.HIGH


def test_poor_partition_pruning_rule(base_snapshot):
    detector = IssueDetector()

    # Setup base pruning conditions
    base_snapshot.query_history["PARTITIONS_SCANNED"] = 800
    base_snapshot.query_history["PARTITIONS_TOTAL"] = 1200
    base_snapshot.query_history["BYTES_SCANNED"] = 2_000_000_000  # 2 GB
    base_snapshot.query_history["ROWS_PRODUCED"] = 100            # Low output

    # Medium Pruning: ratio 800 / 1200 = 0.66
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 1
    assert issues[0].type == IssueType.POOR_PARTITION_PRUNING
    assert issues[0].severity == IssueSeverity.MEDIUM

    # High Pruning: ratio 1000 / 1200 = 0.83
    base_snapshot.query_history["PARTITIONS_SCANNED"] = 1000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert issues[0].severity == IssueSeverity.HIGH


def test_expensive_join_rule(base_snapshot):
    detector = IssueDetector()
    
    # Trigger Stage 1 Suspicion: rows_produced > 10M
    base_snapshot.query_history["ROWS_PRODUCED"] = 15_000_000
    
    # Without stats -> does not fire
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 0

    # With stats confirming high explosion (output 12M, input 10k -> 1200x)
    op_stats = [
        {
            "OPERATOR_TYPE": "HashJoin",
            "OPERATOR_STATISTICS": '{"output_rows": 12000000, "input_rows": 10000}',
            "EXECUTION_TIME_BREAKDOWN": '{"overall_percentage": 0.45}',
        }
    ]
    issues, _ = detector.evaluate_all(base_snapshot, operator_stats=op_stats)
    assert len(issues) == 1
    assert issues[0].type == IssueType.EXPENSIVE_JOIN
    assert issues[0].severity == IssueSeverity.CRITICAL  # Because explosion > 500x


def test_cartesian_join_rule(base_snapshot):
    detector = IssueDetector()
    base_snapshot.query_history["ROWS_PRODUCED"] = 2_000_000

    # With stats confirming cartesian join
    op_stats = [
        {
            "OPERATOR_TYPE": "CartesianJoin",
            "OPERATOR_STATISTICS": '{"output_rows": 2000000}',
            "EXECUTION_TIME_BREAKDOWN": '{}',
        }
    ]
    issues, _ = detector.evaluate_all(base_snapshot, operator_stats=op_stats)
    assert len(issues) == 1
    assert issues[0].type == IssueType.CARTESIAN_JOIN
    assert issues[0].severity == IssueSeverity.CRITICAL


def test_long_running_query_rule(base_snapshot):
    detector = IssueDetector()
    baselines = {
        "long_running": {
            ("COMPUTE_WH", "SELECT"): {"avg_ms": 1_800_000.0, "sample_count": 20}  # 30 mins
        }
    }

    # Under baseline limit (3x baseline is 90 mins = 5,400,000 ms)
    base_snapshot.query_history["EXECUTION_TIME"] = 4_000_000  # ~66 mins
    issues, _ = detector.evaluate_all(base_snapshot, baselines=baselines)
    assert len(issues) == 0

    # Medium: > 3x baseline limit (100 mins = 6,000,000 ms)
    base_snapshot.query_history["EXECUTION_TIME"] = 6_000_000
    issues, _ = detector.evaluate_all(base_snapshot, baselines=baselines)
    assert len(issues) == 1
    assert issues[0].type == IssueType.LONG_RUNNING_QUERY
    assert issues[0].severity == IssueSeverity.MEDIUM

    # High: > 6x baseline limit (190 mins = 11,400,000 ms)
    base_snapshot.query_history["EXECUTION_TIME"] = 11_400_000
    issues, _ = detector.evaluate_all(base_snapshot, baselines=baselines)
    assert issues[0].severity == IssueSeverity.HIGH


def test_queue_overload_rule(base_snapshot):
    detector = IssueDetector()

    # Above 5 min overload queue limit (6 mins)
    base_snapshot.query_history["QUEUED_OVERLOAD_TIME"] = 360000
    base_snapshot.warehouse_load["CLUSTER_COUNT"] = 1
    base_snapshot.warehouse_load["MAX_CLUSTER_COUNT"] = 1  # Ceiling hit

    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 1
    assert issues[0].type == IssueType.QUEUE_OVERLOAD
    assert issues[0].severity == IssueSeverity.HIGH


def test_provisioning_delay_rule(base_snapshot):
    detector = IssueDetector()

    # Above 45s floor (50 seconds)
    base_snapshot.query_history["QUEUED_PROVISIONING_TIME"] = 50000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 1
    assert issues[0].type == IssueType.PROVISIONING_DELAY
    assert issues[0].severity == IssueSeverity.LOW


def test_transaction_blocked_rule(base_snapshot):
    detector = IssueDetector()

    # Blocked for 2 minutes
    base_snapshot.query_history["TRANSACTION_BLOCKED_TIME"] = 120000
    issues, _ = detector.evaluate_all(base_snapshot)
    assert len(issues) == 1
    assert issues[0].type == IssueType.TRANSACTION_BLOCKED
    assert issues[0].severity == IssueSeverity.HIGH


def test_high_network_shuffle_rule(base_snapshot):
    detector = IssueDetector()
    base_snapshot.query_history["WAREHOUSE_SIZE"] = "Large"  # 256 GB RAM
    base_snapshot.query_history["BYTES_SCANNED"] = 150_000_000_000  # 150 GB

    # Total network shuffle bytes: 140 GB (> 50% of Large WH RAM = 128 GB)
    op_stats = [
        {
            "OPERATOR_TYPE": "TableScan",
            "OPERATOR_STATISTICS": '{"network_bytes": 150000000000}',
        }
    ]
    issues, _ = detector.evaluate_all(base_snapshot, operator_stats=op_stats)
    assert len(issues) == 1
    assert issues[0].type == IssueType.HIGH_NETWORK_SHUFFLE
    assert issues[0].severity == IssueSeverity.MEDIUM


def test_cost_anomaly_rule(base_snapshot):
    detector = IssueDetector()
    baselines = {
        "cost_anomaly": {
            "COMPUTE_WH": {"avg_credits": 2.0, "stddev_credits": 1.0, "sample_count": 25}
        }
    }

    # Limit = MAX(2 + 3*1, 16) = 16.0.
    # Attributed compute: 20 credits (> 16.0)
    base_snapshot.query_attribution["CREDITS_ATTRIBUTED_COMPUTE"] = 20.0
    issues, _ = detector.evaluate_all(base_snapshot, baselines=baselines)
    assert len(issues) == 1
    assert issues[0].type == IssueType.COST_ANOMALY
    assert issues[0].severity == IssueSeverity.HIGH


def test_evidence_quality_logic(base_snapshot):
    detector = IssueDetector()

    # Complete Snapshot
    _, quality = detector.evaluate_all(base_snapshot)
    assert quality == EvidenceQuality.COMPLETE

    # Partial: missing non-blocking context (e.g. queue load stats)
    base_snapshot.warehouse_load.clear()
    _, quality = detector.evaluate_all(base_snapshot)
    assert quality == EvidenceQuality.PARTIAL

    # Limited: missing primary query history stats
    base_snapshot.query_history.pop("BYTES_SPILLED_TO_REMOTE_STORAGE")
    _, quality = detector.evaluate_all(base_snapshot)
    assert quality == EvidenceQuality.LIMITED
