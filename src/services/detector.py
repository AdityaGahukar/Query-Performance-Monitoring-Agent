import math
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from src.domain.enums import EvidenceQuality, IssueSeverity, IssueType
from src.domain.models import DetectedIssue, TelemetrySnapshot


# Warehouse RAM mapping (in GB)
WH_MEMORY_PROFILE: Dict[str, float] = {
    "X-SMALL": 16.0,
    "XS": 16.0,
    "SMALL": 32.0,
    "S": 32.0,
    "MEDIUM": 64.0,
    "M": 64.0,
    "LARGE": 256.0,
    "L": 256.0,
    "X-LARGE": 1024.0,
    "XL": 1024.0,
    "2X-LARGE": 4096.0,
    "2XL": 4096.0,
    "3X-LARGE": 16384.0,
    "3XL": 16384.0,
    "4X-LARGE": 65536.0,
    "4XL": 65536.0,
}


def get_warehouse_ram_bytes(warehouse_size: Optional[str]) -> Optional[float]:
    """Helper to look up warehouse RAM size in bytes from the approximation table."""
    if not warehouse_size:
        return None
    ram_gb = WH_MEMORY_PROFILE.get(warehouse_size.upper())
    if ram_gb is None:
        return None
    return ram_gb * 1_073_741_824


class BaseRule(ABC):
    """Abstract base class for all deterministic detection rules."""

    @abstractmethod
    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        """Evaluates the snapshot and returns a DetectedIssue if triggered."""
        pass


class RemoteSpillRule(BaseRule):
    """Detection 1 — REMOTE_SPILL"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        bytes_spilled = snapshot.query_history.get("BYTES_SPILLED_TO_REMOTE_STORAGE")
        if bytes_spilled is None or bytes_spilled <= 0:
            return None

        # Severity Logic
        if bytes_spilled <= 10_737_418_240:  # 10 GB
            severity = IssueSeverity.MEDIUM
        elif bytes_spilled <= 53_687_091_200:  # 50 GB
            severity = IssueSeverity.HIGH
        else:
            severity = IssueSeverity.CRITICAL

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.REMOTE_SPILL,
            severity=severity,
            threshold_breached=f"bytes_spilled_to_remote_storage > 0 (actual: {bytes_spilled})",
            actual_value=float(bytes_spilled),
            telemetry_reference=snapshot.snapshot_id,
        )


class LocalSpillRule(BaseRule):
    """Detection 2 — LOCAL_SPILL"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        bytes_spilled = snapshot.query_history.get("BYTES_SPILLED_TO_LOCAL_STORAGE")
        if bytes_spilled is None or bytes_spilled <= 5_368_709_120:  # 5 GB absolute floor
            return None

        wh_size = snapshot.query_history.get("WAREHOUSE_SIZE")
        wh_ram_bytes = get_warehouse_ram_bytes(wh_size)

        if wh_ram_bytes is None:
            # Fallback when warehouse size is unknown/missing
            return DetectedIssue(
                issue_id=uuid4(),
                type=IssueType.LOCAL_SPILL,
                severity=IssueSeverity.LOW,
                threshold_breached=f"bytes_spilled_to_local_storage > 5 GB (actual: {bytes_spilled}) [Warehouse Size Unknown]",
                actual_value=float(bytes_spilled),
                telemetry_reference=snapshot.snapshot_id,
            )

        local_spill_ratio = bytes_spilled / wh_ram_bytes
        if local_spill_ratio <= 0.5:
            return None

        # Severity Logic
        if local_spill_ratio <= 1.0:
            severity = IssueSeverity.LOW
        elif local_spill_ratio <= 2.0:
            severity = IssueSeverity.MEDIUM
        else:
            severity = IssueSeverity.HIGH

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.LOCAL_SPILL,
            severity=severity,
            threshold_breached=f"local_spill_ratio > 0.5 (ratio: {round(local_spill_ratio, 2)}, spilled: {bytes_spilled})",
            actual_value=float(bytes_spilled),
            telemetry_reference=snapshot.snapshot_id,
        )


class PoorPartitionPruningRule(BaseRule):
    """Detection 3 — POOR_PARTITION_PRUNING"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        scanned = snapshot.query_history.get("PARTITIONS_SCANNED")
        total = snapshot.query_history.get("PARTITIONS_TOTAL")
        bytes_scanned = snapshot.query_history.get("BYTES_SCANNED")
        rows_produced = snapshot.query_history.get("ROWS_PRODUCED")

        if scanned is None or total is None or total <= 1000 or scanned <= 0:
            return None
        if bytes_scanned is None or bytes_scanned <= 1_073_741_824:  # 1 GB
            return None

        pruning_ratio = scanned / total
        if pruning_ratio <= 0.5:
            return None

        # Output efficiency check
        # default floor is 1,000 rows expected per partition scanned
        floor_density = 1000
        pruning_efficiency_threshold = scanned * floor_density
        if rows_produced is not None and rows_produced >= pruning_efficiency_threshold:
            return None

        # Severity Logic
        if pruning_ratio <= 0.8:
            severity = IssueSeverity.MEDIUM
        else:
            severity = IssueSeverity.HIGH

        # Annotation check: full_table_scan flag is contextual info
        is_full_table_scan = pruning_ratio > 0.95 and total > 10000
        annotated_breach = f"pruning_ratio > 0.5 (ratio: {round(pruning_ratio, 2)}, total: {total})"
        if is_full_table_scan:
            annotated_breach += " [FULL_TABLE_SCAN]"

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.POOR_PARTITION_PRUNING,
            severity=severity,
            threshold_breached=annotated_breach,
            actual_value=float(pruning_ratio),
            telemetry_reference=snapshot.snapshot_id,
        )


class ExpensiveJoinRule(BaseRule):
    """Detection 4 — EXPENSIVE_JOIN"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        # Stage 1: Suspicion triggers
        rows_produced = snapshot.query_history.get("ROWS_PRODUCED")
        bytes_scanned = snapshot.query_history.get("BYTES_SCANNED")

        suspicious = (rows_produced is not None and rows_produced > 10_000_000) or (
            bytes_scanned is not None and bytes_scanned > 107_374_182_400  # 100 GB
        )
        if not suspicious or not operator_stats:
            return None

        # Stage 2: Confirming using operator stats
        join_types = {"JOIN", "HASHJOIN", "MERGEJOIN"}
        for op in operator_stats:
            op_type = op.get("OPERATOR_TYPE", "").upper()
            if any(jt in op_type for jt in join_types):
                # Parse JSON string values if necessary
                import json
                try:
                    stats_dict = (
                        json.loads(op["OPERATOR_STATISTICS"])
                        if isinstance(op.get("OPERATOR_STATISTICS"), str)
                        else op.get("OPERATOR_STATISTICS", {})
                    )
                    breakdowns = (
                        json.loads(op["EXECUTION_TIME_BREAKDOWN"])
                        if isinstance(op.get("EXECUTION_TIME_BREAKDOWN"), str)
                        else op.get("EXECUTION_TIME_BREAKDOWN", {})
                    )
                except Exception:
                    continue

                output_rows = stats_dict.get("output_rows", 0)
                input_rows = stats_dict.get("input_rows", 0)
                exec_percentage = breakdowns.get("overall_percentage", 0.0)

                if output_rows > 10_000_000 and exec_percentage > 0.3:
                    explosion_factor = output_rows / max(input_rows, 1)
                    if explosion_factor > 50:
                        # Severity Logic
                        if explosion_factor > 500 or output_rows > 1_000_000_000:
                            severity = IssueSeverity.CRITICAL
                        else:
                            severity = IssueSeverity.HIGH

                        return DetectedIssue(
                            issue_id=uuid4(),
                            type=IssueType.EXPENSIVE_JOIN,
                            severity=severity,
                            threshold_breached=f"Join explosion > 50x (output: {output_rows}, factor: {round(explosion_factor, 1)}x)",
                            actual_value=float(explosion_factor),
                            telemetry_reference=snapshot.snapshot_id,
                        )
        return None


class CartesianJoinRule(BaseRule):
    """Detection 5 — CARTESIAN_JOIN"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        # Stage 1: Suspicion trigger
        rows_produced = snapshot.query_history.get("ROWS_PRODUCED")
        if rows_produced is None or rows_produced <= 1_000_000:
            return None

        if not operator_stats:
            return None

        # Stage 2: Confirming cartesian operator type
        cartesian_types = {"CARTESIANJOIN", "NESTEDLOOPJOIN", "CROSS JOIN"}
        for op in operator_stats:
            op_type = op.get("OPERATOR_TYPE", "").upper().replace("-", "").replace(" ", "")
            if any(ct in op_type for ct in cartesian_types):
                import json
                try:
                    stats_dict = (
                        json.loads(op["OPERATOR_STATISTICS"])
                        if isinstance(op.get("OPERATOR_STATISTICS"), str)
                        else op.get("OPERATOR_STATISTICS", {})
                    )
                except Exception:
                    continue

                output_rows = stats_dict.get("output_rows", 0)
                if output_rows > 1_000_000:
                    return DetectedIssue(
                        issue_id=uuid4(),
                        type=IssueType.CARTESIAN_JOIN,
                        severity=IssueSeverity.CRITICAL,
                        threshold_breached=f"CartesianJoin detected with rows > 1M (actual: {output_rows})",
                        actual_value=float(output_rows),
                        telemetry_reference=snapshot.snapshot_id,
                    )
        return None


class LongRunningQueryRule(BaseRule):
    """Detection 6 — LONG_RUNNING_QUERY"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        exec_time = snapshot.query_history.get("EXECUTION_TIME")
        if exec_time is None:
            return None

        wh_name = snapshot.query_history.get("WAREHOUSE_NAME")
        query_type = snapshot.query_history.get("QUERY_TYPE")

        # Baseline lookup
        baseline_avg = None
        if baselines and "long_running" in baselines:
            group_key = (wh_name, query_type)
            stat = baselines["long_running"].get(group_key)
            if stat and stat.get("sample_count", 0) >= 20:
                baseline_avg = stat.get("avg_ms")

        # Threshold formulation
        if baseline_avg:
            threshold = max(baseline_avg * 3.0, 3_600_000)  # 3x baseline or 1 hour floor
        else:
            threshold = 3_600_000  # Flat 1 hour floor

        if exec_time <= threshold:
            return None

        # Severity Logic
        if baseline_avg:
            ratio = exec_time / baseline_avg
            if ratio <= 6.0:
                severity = IssueSeverity.MEDIUM
            elif ratio <= 12.0 or exec_time > 10_800_000:  # 3 hours
                severity = IssueSeverity.HIGH
            else:
                severity = IssueSeverity.CRITICAL
        else:
            # Under flat floor logic
            if exec_time <= 10_800_000:  # 3 hours
                severity = IssueSeverity.MEDIUM
            elif exec_time <= 28_800_000:  # 8 hours
                severity = IssueSeverity.HIGH
            else:
                severity = IssueSeverity.CRITICAL

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.LONG_RUNNING_QUERY,
            severity=severity,
            threshold_breached=f"execution_time > threshold (actual: {exec_time} ms, limit: {threshold} ms)",
            actual_value=float(exec_time),
            telemetry_reference=snapshot.snapshot_id,
        )


class QueueOverloadRule(BaseRule):
    """Detection 7 — QUEUE_OVERLOAD"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        queue_overload = snapshot.query_history.get("QUEUED_OVERLOAD_TIME")
        if queue_overload is None or queue_overload <= 300_000:  # 5 minutes floor
            return None

        # Try to resolve scaling state
        cluster_count = snapshot.warehouse_load.get("CLUSTER_COUNT")
        max_cluster_count = snapshot.warehouse_load.get("MAX_CLUSTER_COUNT")

        # Severity Logic
        if queue_overload > 900_000:  # 15 minutes
            severity = IssueSeverity.CRITICAL
        elif cluster_count is not None and max_cluster_count is not None:
            if cluster_count < max_cluster_count:
                severity = IssueSeverity.MEDIUM  # SCALING_LAG
            else:
                severity = IssueSeverity.HIGH  # CAPACITY_CEILING
        else:
            severity = IssueSeverity.MEDIUM  # Default fallback if load context is missing

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.QUEUE_OVERLOAD,
            severity=severity,
            threshold_breached=f"queued_overload_time > 5 mins (actual: {queue_overload} ms)",
            actual_value=float(queue_overload),
            telemetry_reference=snapshot.snapshot_id,
        )


class ProvisioningDelayRule(BaseRule):
    """Detection 8 — PROVISIONING_DELAY"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        provisioning = snapshot.query_history.get("QUEUED_PROVISIONING_TIME")
        if provisioning is None or provisioning <= 45_000:  # 45 seconds floor
            return None

        # Severity Logic
        if provisioning <= 120_000:  # 2 minutes
            severity = IssueSeverity.LOW
        else:
            severity = IssueSeverity.MEDIUM

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.PROVISIONING_DELAY,
            severity=severity,
            threshold_breached=f"queued_provisioning_time > 45s (actual: {provisioning} ms)",
            actual_value=float(provisioning),
            telemetry_reference=snapshot.snapshot_id,
        )


class TransactionBlockedRule(BaseRule):
    """Detection 9 — TRANSACTION_BLOCKED"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        blocked = snapshot.query_history.get("TRANSACTION_BLOCKED_TIME")
        if blocked is None or blocked <= 60_000:  # 60 seconds floor
            return None

        # Severity Logic
        if blocked <= 300_000:  # 5 minutes
            severity = IssueSeverity.HIGH
        else:
            severity = IssueSeverity.CRITICAL

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.TRANSACTION_BLOCKED,
            severity=severity,
            threshold_breached=f"transaction_blocked_time > 60s (actual: {blocked} ms)",
            actual_value=float(blocked),
            telemetry_reference=snapshot.snapshot_id,
        )


class HighNetworkShuffleRule(BaseRule):
    """Detection 10 — HIGH_NETWORK_SHUFFLE"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        wh_size = snapshot.query_history.get("WAREHOUSE_SIZE")
        wh_ram_bytes = get_warehouse_ram_bytes(wh_size)

        # Single-node warehouses do not experience inter-node network shuffle
        if wh_ram_bytes is None or wh_ram_bytes <= get_warehouse_ram_bytes("MEDIUM"):
            return None

        bytes_scanned = snapshot.query_history.get("BYTES_SCANNED")
        if bytes_scanned is None or bytes_scanned <= 107_374_182_400:  # 100 GB suspicion flag
            return None

        if not operator_stats:
            return None

        # Sum network_bytes across operators
        total_network_bytes = 0
        import json
        for op in operator_stats:
            try:
                stats_dict = (
                    json.loads(op["OPERATOR_STATISTICS"])
                    if isinstance(op.get("OPERATOR_STATISTICS"), str)
                    else op.get("OPERATOR_STATISTICS", {})
                )
            except Exception:
                continue
            total_network_bytes += stats_dict.get("network_bytes", 0)

        # Shuffle thresholds
        shuffle_limit = wh_ram_bytes * 0.5
        if total_network_bytes <= shuffle_limit or total_network_bytes <= 53_687_091_200:  # 50 GB absolute floor
            return None

        # Severity Logic
        if total_network_bytes <= wh_ram_bytes:
            severity = IssueSeverity.MEDIUM
        else:
            severity = IssueSeverity.HIGH

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.HIGH_NETWORK_SHUFFLE,
            severity=severity,
            threshold_breached=f"network_shuffle_bytes > 50% of WH RAM (actual: {total_network_bytes} bytes)",
            actual_value=float(total_network_bytes),
            telemetry_reference=snapshot.snapshot_id,
        )


class CostAnomalyRule(BaseRule):
    """Detection 11 — COST_ANOMALY"""

    def evaluate(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[DetectedIssue]:
        credits = snapshot.query_attribution.get("CREDITS_ATTRIBUTED_COMPUTE")
        if credits is None:
            return None

        wh_name = snapshot.query_history.get("WAREHOUSE_NAME")

        # Baseline lookup
        baseline_avg = None
        baseline_std = None
        if baselines and "cost_anomaly" in baselines and wh_name:
            stat = baselines["cost_anomaly"].get(wh_name)
            if stat and stat.get("sample_count", 0) >= 20:
                baseline_avg = stat.get("avg_credits")
                baseline_std = stat.get("stddev_credits")

        if baseline_avg is not None and baseline_std is not None:
            threshold = max(baseline_avg + (3.0 * baseline_std), 16.0)
        else:
            threshold = 16.0  # 16 credits floor

        if credits <= threshold:
            return None

        # Severity Logic
        if credits > max(3.0 * threshold, 50.0):
            severity = IssueSeverity.CRITICAL
        else:
            severity = IssueSeverity.HIGH

        return DetectedIssue(
            issue_id=uuid4(),
            type=IssueType.COST_ANOMALY,
            severity=severity,
            threshold_breached=f"credits_attributed > threshold (actual: {round(credits, 4)}, limit: {round(threshold, 2)})",
            actual_value=float(credits),
            telemetry_reference=snapshot.snapshot_id,
        )


class IssueDetector:
    """Registry and execution engine for all deterministic rule evaluations."""

    def __init__(self):
        self.rules: List[BaseRule] = [
            RemoteSpillRule(),
            LocalSpillRule(),
            PoorPartitionPruningRule(),
            ExpensiveJoinRule(),
            CartesianJoinRule(),
            LongRunningQueryRule(),
            QueueOverloadRule(),
            ProvisioningDelayRule(),
            TransactionBlockedRule(),
            HighNetworkShuffleRule(),
            CostAnomalyRule(),
        ]

    def determine_evidence_quality(
        self,
        snapshot: TelemetrySnapshot,
        triggered_rules_needing_profile: bool,
        profile_retrieved: bool,
    ) -> EvidenceQuality:
        """Determines the telemetry completeness quality score."""
        # 1. Check if profile retrieval failed when explicitly needed
        if triggered_rules_needing_profile and not profile_retrieved:
            return EvidenceQuality.LIMITED

        # 2. Check if primary telemetry columns are present
        primary_qh_fields = [
            "QUERY_ID",
            "WAREHOUSE_NAME",
            "START_TIME",
            "EXECUTION_TIME",
            "BYTES_SPILLED_TO_REMOTE_STORAGE",
            "BYTES_SPILLED_TO_LOCAL_STORAGE",
            "PARTITIONS_SCANNED",
            "PARTITIONS_TOTAL",
        ]
        for field in primary_qh_fields:
            if snapshot.query_history.get(field) is None:
                return EvidenceQuality.LIMITED

        # 3. Check if secondary telemetry columns or context are missing
        secondary_qh_fields = [
            "ROWS_PRODUCED",
            "BYTES_SCANNED",
            "QUERY_TYPE",
            "TRANSACTION_BLOCKED_TIME",
            "QUEUED_OVERLOAD_TIME",
            "QUEUED_PROVISIONING_TIME",
        ]
        for field in secondary_qh_fields:
            if snapshot.query_history.get(field) is None:
                return EvidenceQuality.PARTIAL

        if not snapshot.warehouse_load or not snapshot.query_attribution:
            return EvidenceQuality.PARTIAL

        return EvidenceQuality.COMPLETE

    def evaluate_all(
        self,
        snapshot: TelemetrySnapshot,
        baselines: Optional[Dict[str, Any]] = None,
        operator_stats: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[DetectedIssue], EvidenceQuality]:
        """Evaluates all rules on the snapshot and computes EvidenceQuality."""
        issues = []
        for rule in self.rules:
            issue = rule.evaluate(snapshot, baselines, operator_stats)
            if issue:
                issues.append(issue)

        # Check if any rule that was triggered required operator stats
        # CartesianJoin, ExpensiveJoin, HighNetworkShuffle require stats
        stage1_expensive_join = (
            snapshot.query_history.get("ROWS_PRODUCED", 0) or 0
        ) > 10_000_000 or (snapshot.query_history.get("BYTES_SCANNED", 0) or 0) > 107_374_182_400
        stage1_cartesian = (snapshot.query_history.get("ROWS_PRODUCED", 0) or 0) > 1_000_000
        stage1_shuffle = (
            snapshot.query_history.get("BYTES_SCANNED", 0) or 0
        ) > 107_374_182_400 and get_warehouse_ram_bytes(
            snapshot.query_history.get("WAREHOUSE_SIZE")
        ) is not None and get_warehouse_ram_bytes(
            snapshot.query_history.get("WAREHOUSE_SIZE")
        ) > get_warehouse_ram_bytes(
            "MEDIUM"
        )

        profile_needed = stage1_expensive_join or stage1_cartesian or stage1_shuffle
        profile_retrieved = operator_stats is not None and len(operator_stats) > 0

        quality = self.determine_evidence_quality(
            snapshot,
            triggered_rules_needing_profile=profile_needed,
            profile_retrieved=profile_retrieved,
        )

        return issues, quality
