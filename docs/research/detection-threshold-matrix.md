# Detection Threshold Matrix

This matrix serves as the quick-reference guide for all candidate detection rules, formulas, and baseline thresholds designed during Phase 2.5. It will directly inform the implementation of `detector.py` in Phase 3.

| Detection | Required Sources | Required Operator Stats | Candidate Formula | Candidate Threshold | Threshold Type |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REMOTE_SPILL** | `QUERY_HISTORY` | `BYTES_SPILLED_REMOTE`, `OPERATOR_TYPE` | `query.bytes_spilled_to_remote_storage` | `> 10 GB` | Absolute |
| **LOCAL_SPILL** | `QUERY_HISTORY` | `BYTES_SPILLED_LOCAL`, `OPERATOR_TYPE` | `query.bytes_spilled_to_local_storage` | `> 25 GB` | Absolute |
| **FULL_TABLE_SCAN** | `QUERY_HISTORY` | `RECORDS_SCANNED` | `partitions_scanned / partitions_total` | `> 0.95` AND `total > 10,000` | Relative |
| **POOR_PARTITION_PRUNING** | `QUERY_HISTORY` | `RECORDS_PRODUCED` | `partitions_scanned / partitions_total` | `> 0.5` AND `produced < 0.01%` | Relative |
| **EXPENSIVE_JOIN** | `OPERATOR_STATS` | `RECORDS_PRODUCED`, `OPERATOR_TYPE` | `operator_out_rows / sum(input_rows)` | `> 100x explosion` | Relative |
| **CARTESIAN_JOIN** | `OPERATOR_STATS` | `OPERATOR_TYPE` | `operator_type == 'CartesianJoin'` | `> 1,000,000 rows` | Absolute |
| **LONG_RUNNING_QUERY** | `QUERY_HISTORY` | N/A | `query.execution_time` | `> 3x 7-day rolling avg` | Baseline |
| **QUEUE_OVERLOAD** | `QUERY_HISTORY`, `WH_LOAD` | N/A | `query.queued_overload_time` | `> 300,000 ms (5 min)` | Absolute |
| **QUEUE_PROVISIONING** | `QUERY_HISTORY` | N/A | `query.queued_provisioning_time` | `> 30,000 ms (30 sec)` | Absolute |
| **TRANSACTION_BLOCKING** | `QUERY_HISTORY` | N/A | `query.transaction_blocked_time` | `> 60,000 ms (1 min)` | Absolute |
| **HIGH_NETWORK_SHUFFLE** | `OPERATOR_STATS` | `NETWORK_BYTES` | `operator.network_bytes` | `> 500 GB` | Absolute |
| **COST_ANOMALY** | `ATTRIBUTION_HISTORY` | N/A | `query.credits_attributed` | `> 50 credits` OR `+3 stddev` | Baseline & Abs |

## Implementation Notes
- **Baseline Types**: Implementing baseline thresholds requires historical state aggregation. For Phase 3 MVP, baseline rules may initially be deployed using generous absolute fallbacks until statistical historical baselines can be computed securely.
- **Operator Dependency**: Rules mapping to `OPERATOR_STATS` are evaluated in a two-stage process. The primary source (e.g. `QUERY_HISTORY`) flags the query, triggering the lazy fetch of operator stats. If operator stats confirm the hypothesis (e.g., exploding join), the specific operator metadata is attached to the issue.
