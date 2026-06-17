# Detection Framework

This document outlines the deterministic Issue Detection Engine architecture for POV-4.

## 1. Supported Issue Catalog
- `REMOTE_SPILL`: High volume of data written to remote storage due to memory exhaustion.
- `LOCAL_SPILL`: Data written to local SSD during sort/join operations.
- `LONG_RUNNING_QUERY`: Query execution time significantly exceeding normal boundaries.
- `QUEUE_WAIT`: Query delayed due to warehouse overloading.
- `WAREHOUSE_SATURATION`: Cluster running at maximum concurrency.
- `COST_ANOMALY`: Account or warehouse-level credit usage exceeds standard patterns.
- `HIGH_CREDIT_CONSUMPTION`: Individual query compute cost is extremely high.
- `PROVISIONING_DELAY`: Wait time due to warehouse startup/resume.
- `CONCURRENCY_BOTTLENECK`: Large number of queued queries despite cluster scaling limits.

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

## 4. Confidence Score Generation Rules
Confidence represents the structural validity and completeness of the finding, generated deterministically by the framework (not the LLM).
- **Base Score**: Starts at `1.0`.
- **Penalty (-0.2)**: If `QUERY_PROFILE` could not be retrieved (timeout/error).
- **Penalty (-0.1)**: If `QUERY_ATTRIBUTION_HISTORY` is lagging and unavailable.
- **Penalty (-0.3)**: If the LLM `AnalysisResult` returned a fallback/default due to a parsing error or timeout.
`confidence_reason` strictly lists the deductions applied (e.g., "0.8 - Query Profile unavailable").

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
5. If `DetectedIssues` > 0, system calculates `confidence_score` deductions based on missing telemetry.
6. Package payload and proceed to RCA phase via LLM.
7. Else, discard snapshot as healthy.
