# Detection Framework

This document outlines the deterministic Issue Detection Engine architecture for POV-4.

## 1. Supported Issue Catalog
- `REMOTE_SPILL`: High volume of data written to remote storage due to memory exhaustion.
- `LOCAL_SPILL`: Data written to local SSD during sort/join operations.
- `POOR_PARTITION_PRUNING`: Excessive I/O scanning due to non-selective query predicates.
- `EXPENSIVE_JOIN`: Join operator causing explosive multiplication of output rows.
- `CARTESIAN_JOIN`: Unintentional Cartesian product producing catastrophic row counts.
- `LONG_RUNNING_QUERY`: Query execution time significantly exceeding normal boundaries.
- `QUEUE_OVERLOAD`: Query delayed in the overload queue due to warehouse capacity ceiling.
- `PROVISIONING_DELAY`: Wait time due to warehouse startup or resume provisioning.
- `TRANSACTION_BLOCKED`: DML statement blocked waiting for a lock held by another transaction.
- `HIGH_NETWORK_SHUFFLE`: Excessive inter-node data redistribution across multi-node warehouses.
- `COST_ANOMALY`: Single query credit cost exceeds historical baseline plus stddev.

## 2. Detection Rules
Rules are mathematically deterministic and evaluated against the `TelemetrySnapshot`. Example implementations:
- **REMOTE_SPILL Rule**: `IF query_history.bytes_spilled_to_remote_storage > CONFIG.SPILL_THRESHOLD_BYTES THEN return DetectedIssue(type="REMOTE_SPILL")`
- **LONG_RUNNING_QUERY Rule**: `IF query_history.execution_time_ms > CONFIG.MAX_EXEC_TIME_MS THEN return DetectedIssue(type="LONG_RUNNING_QUERY")`
- **HIGH_CREDIT_CONSUMPTION Rule**: `IF query_attribution.credits_attributed > CONFIG.QUERY_CREDIT_THRESHOLD THEN return DetectedIssue(type="HIGH_CREDIT_CONSUMPTION")`

## 3. Severity Calculation Rules
Severity is computed deterministically per issue based on thresholds:
- **LOW**: Below moderate threshold (e.g., 100MB-500MB remote spill).
- **MEDIUM**: Moderate threshold breached, low cost impact.
- **HIGH**: Large threshold breached OR cost > $X.
- **CRITICAL**: Extreme threshold breached, causing systemic slowdowns or massive cost overruns.

*Overall `PerformanceFinding` severity inherits the highest individual `DetectedIssue` severity.*

## 4. Telemetry Evidence Quality Assessment
To represent telemetry completeness, the system assigns an `EvidenceQuality` level to the `PerformanceFinding`:
- **COMPLETE**: All telemetry sources, including lazy-loaded query operator stats, are successfully retrieved and present.
- **PARTIAL**: Basic execution statistics are present, but non-blocking enrichment data (e.g., lag in `QUERY_ATTRIBUTION_HISTORY` or failure to fetch `operator_stats`) is missing.
- **LIMITED**: Significant telemetry is missing, indicating a sparse snapshot (e.g., only QUERY_HISTORY was successfully loaded).

## 5. Issue-to-Telemetry Mapping
Detection relies strictly on core telemetry metrics:
- `REMOTE_SPILL` & `LONG_RUNNING_QUERY` -> Detected via `QUERY_HISTORY`
- `WAREHOUSE_SATURATION` -> Detected via `WAREHOUSE_LOAD_HISTORY`
- `HIGH_CREDIT_CONSUMPTION` -> Detected via `METERING_HISTORY` and `QUERY_ATTRIBUTION_HISTORY`
*(See `docs/telemetry/issue-to-telemetry-mapping.md` for the full matrix).*

## 6. Detection Processing Flow
1. Receive `TelemetrySnapshot` from Data Collection Layer.
2. Iterate through Rule Registry.
3. For each Rule, invoke `evaluate(snapshot)`.
4. If threshold breached, instantiate `DetectedIssue` with calculated severity.
5. If `DetectedIssues` > 0, system determines `evidence_quality` based on telemetry completeness.
6. Package payload and proceed to RCA phase via LLM.
7. Else, discard snapshot as healthy.
