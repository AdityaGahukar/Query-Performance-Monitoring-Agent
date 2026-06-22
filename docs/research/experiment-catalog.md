# Experiment Catalog (TPC-H)

This catalog defines the empirical experiments required to validate the detection rules and calibrate thresholds. Experiments are mapped against standard TPC-H datasets available in Snowflake (`SNOWFLAKE_SAMPLE_DATA.TPCH_SF100` and `TPCH_SF1000`).

## 1. REMOTE_SPILL & LOCAL_SPILL
**Goal**: Identify the exact tipping point where an X-Small warehouse exhausts RAM and SSD.

### SF100 Setup
- **Good Query**: Standard aggregations on `ORDERS` grouped by `O_CUSTKEY`.
- **Bad Query**: `SELECT * FROM TPCH_SF100.LINEITEM ORDER BY L_EXTENDEDPRICE, L_SHIPDATE, L_COMMITDATE;` (Executed on X-Small).
- **Expected Telemetry Signatures**: Massive `BYTES_SPILLED_TO_LOCAL_STORAGE`.
- **Metrics to capture**: `EXECUTION_TIME`, `BYTES_SPILLED_LOCAL`.
- **Observations to record**: At what GB mark does the spill occur on X-Small vs Small?

### SF1000 Setup
- **Good Query**: Highly filtered `ORDER BY` with `LIMIT 100`.
- **Bad Query**: Massive sort on `TPCH_SF1000.LINEITEM` (6 billion rows).
- **Expected Telemetry Signatures**: Local disk fills up, resulting in massive `BYTES_SPILLED_TO_REMOTE_STORAGE`.
- **Metrics to capture**: Remote spill volume, query execution cost.
- **Observations to record**: Ratio of local to remote spill.

## 2. EXPENSIVE_JOIN & CARTESIAN_JOIN
**Goal**: Observe row explosions.

### SF100 Setup
- **Good Query**: Join `ORDERS` and `LINEITEM` on `O_ORDERKEY = L_ORDERKEY`.
- **Bad Query**: Join `ORDERS` and `LINEITEM` on `O_ORDERSTATUS = L_RETURNFLAG`.
- **Expected Telemetry Signatures**: `RECORDS_PRODUCED` outpaces `RECORDS_SCANNED` by millions.
- **Metrics to capture**: Operator-level `RECORDS_PRODUCED`, `EXECUTION_TIME_FRACTION`.
- **Observations to record**: LLM's ability to isolate the specific exploding join node.

### SF1000 Setup
- **Good Query**: standard inner joins with highly selective filters.
- **Bad Query**: Cross join of `NATION`, `REGION`, and subset of `ORDERS` without filters.
- **Expected Telemetry Signatures**: High CPU utilization, potential spill.
- **Metrics to capture**: Cost attribution.
- **Observations to record**: Time to cancel query vs time to execute.

## 3. FULL_TABLE_SCAN & POOR_PARTITION_PRUNING
**Goal**: Differentiate necessary scans from inefficient filtering.

### SF100 Setup
- **Good Query**: `SELECT SUM(L_QUANTITY) FROM LINEITEM WHERE L_SHIPDATE = '1996-01-01'`.
- **Bad Query**: `SELECT SUM(L_QUANTITY) FROM LINEITEM WHERE YEAR(L_SHIPDATE) = 1996 AND LOWER(L_RETURNFLAG) = 'r'`.
- **Expected Telemetry Signatures**: High `PARTITIONS_SCANNED`, near 100% of `PARTITIONS_TOTAL`.
- **Metrics to capture**: Partition scan ratio.
- **Observations to record**: Does the optimizer rewrite the function? Is pruning defeated?

### SF1000 Setup
- **Good Query**: Query utilizing existing micro-partition clustering.
- **Bad Query**: Filtering by an unclustered, high-cardinality UUID column using `LIKE '%xxx%'`.
- **Expected Telemetry Signatures**: 100% partition scan with < 0.01% records produced.
- **Metrics to capture**: `RECORDS_SCANNED` vs `RECORDS_PRODUCED`.
- **Observations to record**: Time difference compared to properly pruned queries.

## 4. QUEUE_OVERLOAD
**Goal**: Induce concurrency bottlenecks.

### SF100 Setup
- **Setup**: Limit warehouse to MAX_CLUSTER_COUNT = 1.
- **Bad Behavior**: Run 100 parallel python threads submitting the SF100 complex join queries simultaneously.
- **Expected Telemetry Signatures**: Spikes in `AVG_QUEUED_LOAD` in `WAREHOUSE_LOAD_HISTORY`, and `QUEUED_OVERLOAD_TIME` in `QUERY_HISTORY`.
- **Metrics to capture**: Queue wait time percentiles (p50, p90, p99).
- **Observations to record**: Does the queue time eventually exceed the execution time?

### SF1000 Setup
- **Setup**: Trigger heavy ETL streams simultaneously.
- **Metrics to capture**: Same as above, focusing on multi-cluster warehouse scale-out delays.

## 5. COST_ANOMALY
**Goal**: Correlate expensive execution with actual credit deductions.

### SF1000 Setup
- **Bad Query**: Massive cross-product or complex window function over a multi-billion row dataset, allowed to run for exactly 1 hour before cancellation.
- **Expected Telemetry Signatures**: Large `CREDITS_ATTRIBUTED_COMPUTE` value explicitly tied to the `QUERY_ID`.
- **Metrics to capture**: `CREDITS_ATTRIBUTED_COMPUTE`.
- **Observations to record**: Latency between query completion and the appearance of data in `QUERY_ATTRIBUTION_HISTORY` (up to 24h expected).
