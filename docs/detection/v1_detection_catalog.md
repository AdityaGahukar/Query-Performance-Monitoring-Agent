# V1 Detection Catalog

**Path**: `docs/detection/v1_detection_catalog.md`
**Status**: Implementation contract for Phase 3
**Validated against**: TPCH_SF100, Snowflake trial account (X-Small → X-Large)

---

## Centralized Rules

### 1. Telemetry Evidence Quality Assessment
Rather than repeating criteria per detection, the system assigns an `EvidenceQuality` level to `PerformanceFinding` based on the status of required fields:
* **`COMPLETE`**: All required fields (Primary and Secondary) are present and non-null.
* **`PARTIAL`**: All Primary fields are present, but one or more Secondary/Enrichment fields are null (detection still fires).
* **`LIMITED`**: Primary telemetry fields are present, but crucial diagnostic stats (e.g. failure to retrieve `operator_stats` via `GET_QUERY_OPERATOR_STATS`) are unavailable.

*Note: Telemetry completeness does not gate or suppress deterministic detection rules.*

### 2. Warehouse Memory Approximations
Since Snowflake does not expose warehouse RAM, the detector uses this configuration table (stored in `POV4.WH_MEMORY_PROFILE` and joined via `WAREHOUSE_SIZE`):

| Warehouse Size | Total RAM | Nodes | Slots |
|---|---|---|---|
| X-Small | 16 GB | 1 | 8 |
| Small | 32 GB | 1 | 8 |
| Medium | 64 GB | 1 | 8 |
| Large | 256 GB | 2 | 8 |
| X-Large | 1,024 GB | 4 | 8 |
| 2X-Large | 4,096 GB | 8 | 8 |
| 3X-Large | 16,384 GB | 16 | 8 |
| 4X-Large | 65,536 GB | 32 | 8 |

---

## Detection Index

| # | Detection | Severity Range | Telemetry Layer | `GET_QUERY_OPERATOR_STATS` |
|---|---|---|---|---|
| 1 | REMOTE_SPILL | MEDIUM → CRITICAL | Layer 1 (`QUERY_HISTORY`) | No |
| 2 | LOCAL_SPILL | LOW → HIGH | Layer 1 & Memory Profile | No |
| 3 | POOR_PARTITION_PRUNING | MEDIUM → HIGH | Layer 1 (`QUERY_HISTORY`) | No |
| 4 | EXPENSIVE_JOIN | HIGH → CRITICAL | Layer 2 (`OPERATOR_STATS`) | **Yes** |
| 5 | CARTESIAN_JOIN | CRITICAL | Layer 2 (`OPERATOR_STATS`) | **Yes** |
| 6 | LONG_RUNNING_QUERY | MEDIUM → CRITICAL | Layer 1 & Baseline statistics | No |
| 7 | QUEUE_OVERLOAD | MEDIUM → CRITICAL | Layer 1 & Concurrency context | No |
| 8 | PROVISIONING_DELAY | LOW → MEDIUM | Layer 1 (`QUERY_HISTORY`) | No |
| 9 | TRANSACTION_BLOCKED | HIGH → CRITICAL | Layer 1 (`QUERY_HISTORY`) | No |
| 10 | HIGH_NETWORK_SHUFFLE | MEDIUM → HIGH | Layer 2 & Memory Profile | **Yes** |
| 11 | COST_ANOMALY | HIGH → CRITICAL | Daily attribution batch | No |

---

## Detection 1 — REMOTE_SPILL

* **Business Impact**: Writing temporary data to remote object storage is 10–100x slower than memory, causing massive query slowdowns and inflating compute cost.
* **Telemetry Fields**: 
  - `BYTES_SPILLED_TO_REMOTE_STORAGE` (Source: `QUERY_HISTORY`) **[Primary]**
  - `WAREHOUSE_SIZE` (Source: `QUERY_HISTORY`) **[Secondary]**
  - `EXECUTION_TIME` (Source: `QUERY_HISTORY`) **[Secondary]**
* **Formula**: `bytes_spilled_to_remote_storage > 0`
* **Severity Logic**:
  - **MEDIUM**: Spill volume `≤ 10 GB` (10,737,418,240 bytes)
  - **HIGH**: Spill volume `> 10 GB` and `≤ 50 GB`
  - **CRITICAL**: Spill volume `> 50 GB` (53,687,091,200 bytes)
* **False-Positive Controls**: None. Any remote spill is anomalous and actionable.
* **Operator Statistics**: Optional (to identify the spilling operator).
* **Example Triggering Query**:
  ```sql
  -- Force large sort to overflow RAM on an X-Small warehouse
  SELECT * FROM large_fact_table ORDER BY col_a DESC, col_b ASC;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Small filtered sort that easily fits in RAM
  SELECT * FROM large_fact_table WHERE event_date = '2024-01-01' ORDER BY revenue DESC LIMIT 1000;
  ```

---

## Detection 2 — LOCAL_SPILL

* **Business Impact**: Spilling data to local SSD degrades execution throughput for the query and slows down concurrent workloads sharing the node.
* **Telemetry Fields**:
  - `BYTES_SPILLED_TO_LOCAL_STORAGE` (Source: `QUERY_HISTORY`) **[Primary]**
  - `WAREHOUSE_SIZE` (Source: `QUERY_HISTORY`) **[Primary]** (used to retrieve `wh_total_ram_gb`)
* **Formula**: `local_spill_ratio > 0.5` AND `bytes_spilled_to_local_storage > 5 GB`
  *(Where `local_spill_ratio = bytes_spilled_to_local_storage / (wh_total_ram_gb * 1,073,741,824)`)*
* **Severity Logic**:
  - **LOW**: `0.5 < local_spill_ratio ≤ 1.0`
  - **MEDIUM**: `1.0 < local_spill_ratio ≤ 2.0`
  - **HIGH**: `local_spill_ratio > 2.0`
* **False-Positive Controls**:
  - `bytes_spilled_to_local_storage > 5 GB` floor filters out minor, non-blocking spills.
  - If `WAREHOUSE_SIZE` is null (e.g. serverless tasks), skips ratio calculation and uses a flat `> 5 GB` threshold.
* **Operator Statistics**: Optional.
* **Example Triggering Query**:
  ```sql
  -- Large join on low-cardinality fields on a Small warehouse (32 GB RAM)
  SELECT a.*, b.* FROM table_a a JOIN table_b b ON a.id = b.id;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Same query run on a Large warehouse (256 GB RAM) where spill ratio remains < 0.5
  SELECT a.*, b.* FROM table_a a JOIN table_b b ON a.id = b.id;
  ```

---

## Detection 3 — POOR_PARTITION_PRUNING

* **Business Impact**: Non-sargable query predicates (e.g., functions on columns or leading wildcards) force Snowflake to scan all micro-partitions, wasting I/O and compute.
* **Telemetry Fields**:
  - `PARTITIONS_SCANNED` (Source: `QUERY_HISTORY`) **[Primary]**
  - `PARTITIONS_TOTAL` (Source: `QUERY_HISTORY`) **[Primary]**
  - `BYTES_SCANNED` (Source: `QUERY_HISTORY`) **[Secondary]**
  - `ROWS_PRODUCED` (Source: `QUERY_HISTORY`) **[Secondary]**
* **Formula**: `pruning_ratio > 0.5` AND `partitions_total > 1,000` AND `bytes_scanned > 1 GB` AND `rows_produced < (partitions_scanned * pruning_row_density_floor)`
  *(Where `pruning_ratio = partitions_scanned / partitions_total` and default `pruning_row_density_floor = 1,000`)*
* **Severity Logic**:
  - **MEDIUM**: `0.5 < pruning_ratio ≤ 0.8` (under poor-output efficiency guard)
  - **HIGH**: `pruning_ratio > 0.8` (under poor-output efficiency guard)
  - *Annotation: Attach `full_table_scan: true` if `pruning_ratio > 0.95` and `partitions_total > 10,000`.*
* **False-Positive Controls**:
  - `partitions_total > 1,000` and `bytes_scanned > 1 GB` suppress notifications for trivial/small tables.
  - The output efficiency guard prevents flagging intentional full-table aggregate scans.
* **Operator Statistics**: No.
* **Example Triggering Query**:
  ```sql
  -- Wrapping column in YEAR() prevents metadata pruning
  SELECT SUM(L_QUANTITY) FROM lineitem WHERE YEAR(L_SHIPDATE) = 2024 AND LOWER(L_RETURNFLAG) = 'r';
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Normal full aggregate table group-by (fails output efficiency guard as it returns many rows)
  SELECT YEAR(O_ORDERDATE), SUM(O_TOTALPRICE) FROM orders GROUP BY 1;
  ```

---

## Detection 4 — EXPENSIVE_JOIN

* **Business Impact**: Joining tables on low-cardinality keys causes explosive fan-out, generating massive intermediate rows that stall down-stream execution.
* **Telemetry Fields**:
  - `ROWS_PRODUCED` (Source: `QUERY_HISTORY`) **[Primary]** (Suspicion trigger: `> 10,000,000` rows)
  - `BYTES_SCANNED` (Source: `QUERY_HISTORY`) **[Primary]** (Suspicion trigger: `> 100 GB` scanned)
  - `OPERATOR_TYPE` (Source: `OPERATOR_STATS`) **[Primary]** (Must match `Join`, `HashJoin`, `MergeJoin`)
  - `input_rows` & `output_rows` (Source: `OPERATOR_STATS`) **[Primary]**
  - `overall_percentage` (Source: `OPERATOR_STATS:execution_time_breakdown`) **[Primary]**
* **Formula**: `operator_type` in join list AND `explosion_factor > 50` AND `operator_output_rows > 10,000,000` AND `execution_time_fraction > 0.3`
  *(Where `explosion_factor = operator_output_rows / NULLIF(operator_input_rows, 0)`)*
* **Severity Logic**:
  - **HIGH**: Fulfills the primary formula criteria.
  - **CRITICAL**: `explosion_factor > 500` OR `operator_output_rows > 1,000,000,000`.
* **False-Positive Controls**:
  - Requires `operator_output_rows > 10M` and the operator to be responsible for `> 30%` of total execution time.
* **Operator Statistics**: **Yes (Layer 2 verification required)**.
* **Example Triggering Query**:
  ```sql
  -- Join on low-cardinality flags causing billions of matching row evaluations
  SELECT O.O_ORDERSTATUS, L.L_RETURNFLAG FROM orders O JOIN lineitem L ON O.O_ORDERSTATUS = L.L_RETURNFLAG;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Correct join on high-cardinality key columns
  SELECT O.O_ORDERKEY, COUNT(L.L_LINENUMBER) FROM orders O JOIN lineitem L ON O.O_ORDERKEY = L.L_ORDERKEY GROUP BY 1;
  ```

---

## Detection 5 — CARTESIAN_JOIN

* **Business Impact**: Accidental cross joins scale exponentially, exhausting warehouse memory and resulting in query crashes or multi-hour execution hangs.
* **Telemetry Fields**:
  - `ROWS_PRODUCED` (Source: `QUERY_HISTORY`) **[Primary]** (Suspicion trigger: `> 1,000,000`)
  - `OPERATOR_TYPE` (Source: `OPERATOR_STATS`) **[Primary]** (Matches `CartesianJoin`, `NestedLoopJoin`, `Cross Join`)
  - `output_rows` (Source: `OPERATOR_STATS:OPERATOR_STATISTICS`) **[Primary]**
* **Formula**: Cartesian operator type match AND `operator_output_rows > 1,000,000`
* **Severity Logic**: **CRITICAL** (Always, if rows threshold crossed).
* **False-Positive Controls**: `operator_output_rows > 1,000,000` preserves small lookup-table cross joins.
* **Operator Statistics**: **Yes (Layer 2 verification required)**.
* **Example Triggering Query**:
  ```sql
  -- Comma-separated FROM clause with missing join filter
  SELECT N.N_NAME, O.O_ORDERKEY FROM nation N, orders O WHERE O.O_ORDERDATE > '2024-01-01';
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Intentional small lookup cross join (produces only 125 rows)
  SELECT N.N_NAME, R.R_NAME FROM nation N CROSS JOIN region R;
  ```

---

## Detection 6 — LONG_RUNNING_QUERY

* **Business Impact**: Runaway queries consume warehouse execution capacity, queuing other DML/SELECT operations and wasting compute credits.
* **Telemetry Fields**:
  - `EXECUTION_TIME` (Source: `QUERY_HISTORY`) **[Primary]**
  - `WAREHOUSE_NAME` (Source: `QUERY_HISTORY`) **[Primary]**
  - `QUERY_TYPE` (Source: `QUERY_HISTORY`) **[Primary]**
  - `baseline_avg_ms` (Source: `POV4.DETECTION_BASELINES`) **[Secondary]**
* **Formula**: `execution_time > long_run_threshold_ms`
  *(Where `long_run_threshold_ms = MAX(baseline_avg_ms * 3.0, 3,600,000 ms)`)*
* **Severity Logic**:
  - **MEDIUM**: `3x baseline < execution_time ≤ 6x baseline`
  - **HIGH**: `execution_time > 6x baseline` OR `> 3 hours` (10,800,000 ms)
  - **CRITICAL**: `execution_time > 12x baseline` OR `> 8 hours` (28,800,000 ms)
* **False-Positive Controls**:
  - Threshold evaluates dynamically per `(warehouse_name, query_type)`.
  - Baselines require `sample_count >= 20` over a 30-day window; otherwise falls back to a flat `1 hour` floor.
* **Operator Statistics**: No.
* **Example Triggering Query**:
  ```sql
  -- Regressed query missing cluster key filters (takes 8 mins vs 30s baseline)
  SELECT customer_id, SUM(order_value) FROM orders WHERE status = 'completed' GROUP BY 1;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Normal nightly ETL MERGE matching its 45-minute average baseline
  MERGE INTO fact_sales USING staging_sales ...;
  ```

---

## Detection 7 — QUEUE_OVERLOAD

* **Business Impact**: Queries stuck in queue miss service SLAs, indicating that the warehouse has hit its capacity sizing limits or scaling policy limits.
* **Telemetry Fields**:
  - `QUEUED_OVERLOAD_TIME` (Source: `QUERY_HISTORY`) **[Primary]**
  - `EXECUTION_TIME` (Source: `QUERY_HISTORY`) **[Secondary]**
  - `QUEUED_PROVISIONING_TIME` (Source: `QUERY_HISTORY`) **[Secondary]**
  - `TRANSACTION_BLOCKED_TIME` (Source: `QUERY_HISTORY`) **[Secondary]**
  - `CLUSTER_COUNT` (Source: `WAREHOUSE_LOAD_HISTORY`) **[Secondary]**
  - `MAX_CLUSTER_COUNT` (Source: `WAREHOUSES`) **[Secondary]**
* **Formula**: `queued_overload_time > 300,000 ms` (5 minutes)
* **Severity Logic**:
  - **MEDIUM**: `queued_overload_time > 5 mins` AND `cluster_count < max_cluster_count` (Scaling Lag)
  - **HIGH**: `queued_overload_time > 5 mins` AND `cluster_count = max_cluster_count` (Capacity Ceiling)
  - **CRITICAL**: `queued_overload_time > 900,000 ms` (15 minutes) regardless of scaling state
* **False-Positive Controls**:
  - `5 minutes` minimum wait floor absorbs temporary transient load spikes.
* **Operator Statistics**: No.
* **Example Triggering Query**:
  ```sql
  -- Submit 50 concurrent queries to a single-cluster X-Small warehouse
  SELECT L_ORDERKEY, SUM(L_QUANTITY) FROM lineitem GROUP BY 1 ORDER BY 2 DESC LIMIT 100;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Same query run on an auto-scaling warehouse that absorbs the load immediately
  SELECT L_ORDERKEY, SUM(L_QUANTITY) FROM lineitem GROUP BY 1 ORDER BY 2 DESC LIMIT 100;
  ```

---

## Detection 8 — PROVISIONING_DELAY

* **Business Impact**: Abnormal resume delay indicates cloud infrastructure provisioning bottlenecks, extending apparent user latency.
* **Telemetry Fields**:
  - `QUEUED_PROVISIONING_TIME` (Source: `QUERY_HISTORY`) **[Primary]**
  - `WAREHOUSE_NAME` (Source: `QUERY_HISTORY`) **[Secondary]**
* **Formula**: `queued_provisioning_time > 45,000 ms` (45 seconds)
* **Severity Logic**:
  - **LOW**: `45,000 ms < queued_provisioning_time ≤ 120,000 ms`
  - **MEDIUM**: `queued_provisioning_time > 120,000 ms` (2 minutes)
* **False-Positive Controls**:
  - `45 seconds` threshold prevents alerts on typical trial/shared-infrastructure cold start latency (usually 10–30s).
* **Operator Statistics**: No.
* **Example Triggering Query**:
  ```sql
  -- First query on a suspended warehouse that stalls for 90s during resume
  SELECT 1;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Query executed against an already running warehouse (provisioning = 0s)
  SELECT COUNT(*) FROM orders;
  ```

---

## Detection 9 — TRANSACTION_BLOCKED

* **Business Impact**: Blocked DML statements cannot complete, indicating uncommitted transaction blocks or connection locks.
* **Telemetry Fields**:
  - `TRANSACTION_BLOCKED_TIME` (Source: `QUERY_HISTORY`) **[Primary]**
  - `QUERY_TYPE` (Source: `QUERY_HISTORY`) **[Secondary]**
* **Formula**: `transaction_blocked_time > 60,000 ms` (60 seconds)
* **Severity Logic**:
  - **HIGH**: `60,000 ms < transaction_blocked_time ≤ 300,000 ms`
  - **CRITICAL**: `transaction_blocked_time > 300,000 ms` (5 minutes lock wait)
* **False-Positive Controls**:
  - `60 seconds` wait floor isolates systemic blocked transaction locks from fast row updates.
* **Operator Statistics**: No.
* **Example Triggering Query**:
  ```sql
  -- Session B trying to update a row locked in Session A
  UPDATE orders SET status = 'processed' WHERE order_id = 12345;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Update statement executed when no locks are held
  UPDATE orders SET status = 'processed' WHERE order_id = 12345;
  ```

---

## Detection 10 — HIGH_NETWORK_SHUFFLE

* **Business Impact**: Mass inter-node data transfer across multi-node warehouses (Large+) saturates networks, slowing down execution plans.
* **Telemetry Fields**:
  - `BYTES_SCANNED` (Source: `QUERY_HISTORY`) **[Primary]** (Suspicion trigger: `> 100 GB`)
  - `WAREHOUSE_SIZE` (Source: `QUERY_HISTORY`) **[Primary]**
  - `network_bytes` (Source: `OPERATOR_STATS:OPERATOR_STATISTICS`) **[Primary]**
* **Formula**: `operator_network_bytes > (wh_total_ram_gb * 1,073,741,824 * 0.5)` AND `operator_network_bytes > 50 GB`
  *(Note: Network shuffle does not occur on single-node warehouses: X-Small, Small, and Medium).*
* **Severity Logic**:
  - **MEDIUM**: `50% of WH RAM < network_bytes ≤ 100% of WH RAM`
  - **HIGH**: `network_bytes > 100% of WH RAM`
* **False-Positive Controls**:
  - `50 GB` floor and WH RAM ratio prevent alerts on typical distributed aggregations.
* **Operator Statistics**: **Yes (Layer 2 verification required)**.
* **Example Triggering Query**:
  ```sql
  -- Large aggregation on a non-clustered high-cardinality key on a Large warehouse
  SELECT customer_uuid, SUM(event_value) FROM billion_row_events GROUP BY customer_uuid;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Same query run on an X-Small warehouse (single-node, no shuffle occurs)
  SELECT customer_uuid, SUM(event_value) FROM billion_row_events GROUP BY customer_uuid;
  ```

---

## Detection 11 — COST_ANOMALY

* **Business Impact**: Runs daily to isolate runaway queries or regression spikes that consumed highly anomalous amounts of billing credits.
* **Telemetry Fields**:
  - `CREDITS_ATTRIBUTED_COMPUTE` (Source: `QUERY_ATTRIBUTION_HISTORY`) **[Primary]**
  - `WAREHOUSE_NAME` (Source: `QUERY_ATTRIBUTION_HISTORY`) **[Primary]**
  - `baseline_avg_credits` & `baseline_stddev_credits` (Source: `POV4.DETECTION_BASELINES`) **[Secondary]**
* **Formula**: `credits_attributed_compute > cost_anomaly_threshold`
  *(Where `cost_anomaly_threshold = MAX(baseline_avg_credits + 3*baseline_stddev_credits, 16.0)`)*
* **Severity Logic**:
  - **HIGH**: Attributed credits cross the `cost_anomaly_threshold`.
  - **CRITICAL**: Attributed credits cross `MAX(3 * cost_anomaly_threshold, 50.0)`.
* **False-Positive Controls**:
  - `3 * stddev` threshold multiplier filters out standard variance.
  - Per-warehouse stats ensure queries are only compared to their execution cluster size.
  - `16.0` credit absolute floor filters out cheap query fluctuations.
* **Operator Statistics**: No.
* **Example Triggering Query**:
  ```sql
  -- Accidental cross join allowed to run on a Large warehouse for 45 minutes (costs 6 credits vs 0.25 threshold)
  SELECT N.N_NAME, S.S_NAME FROM nation N CROSS JOIN supplier S CROSS JOIN orders O;
  ```
* **Example Non-Triggering Query**:
  ```sql
  -- Normal nightly large ETL (consumes 9.5 credits vs dynamic threshold of 11.6)
  MERGE INTO fact_orders USING staging_orders ...;
  ```

---

## Catalog Summary

| Detection | Trigger Condition (abbreviated) | Severity | `GET_QUERY_OPERATOR_STATS` | Daily Batch |
|---|---|---|---|---|
| REMOTE_SPILL | `bytes_spilled_remote > 0` | MEDIUM → CRITICAL | No | No |
| LOCAL_SPILL | `local_spill_ratio > 0.5` AND `> 5 GB` | LOW → HIGH | No | No |
| POOR_PARTITION_PRUNING | `pruning_ratio > 0.5` AND output efficiency below floor | MEDIUM → HIGH | No | No |
| EXPENSIVE_JOIN | `explosion_factor > 50` AND `output > 10M` AND `exec_fraction > 0.3` | HIGH → CRITICAL | **Yes** | No |
| CARTESIAN_JOIN | operator type match AND `output > 1M` | CRITICAL | **Yes** | No |
| LONG_RUNNING_QUERY | `execution_time > MAX(3x baseline, 1 hour)` | MEDIUM → CRITICAL | No | No |
| QUEUE_OVERLOAD | `queued_overload_time > 5 min` | MEDIUM → CRITICAL | No | No |
| PROVISIONING_DELAY | `queued_provisioning_time > 45 sec` | LOW → MEDIUM | No | No |
| TRANSACTION_BLOCKED | `transaction_blocked_time > 60 sec` | HIGH → CRITICAL | No | No |
| HIGH_NETWORK_SHUFFLE | `network_bytes > 50% of WH RAM` AND `> 50 GB` | MEDIUM → HIGH | **Yes** | No |
| COST_ANOMALY | `credits > MAX(avg + 3σ, 16)` | HIGH → CRITICAL | No | **Yes** |
