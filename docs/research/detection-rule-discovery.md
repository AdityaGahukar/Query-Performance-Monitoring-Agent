# Detection Rule Discovery Framework

This document outlines the theoretical foundation and required attributes for every potential performance issue the POV-4 Detection Engine aims to identify.

## 1. REMOTE_SPILL
1. **Business impact**: Severe query slowdowns; writing temporary data to cloud storage is exceptionally slow and consumes compute credits for extended durations.
2. **Detection evidence**: Data volume logged in `BYTES_SPILLED_TO_REMOTE_STORAGE`.
3. **Required telemetry sources**: `QUERY_HISTORY`.
4. **Required operator statistics fields**: `OPERATOR_ID`, `OPERATOR_TYPE`, `BYTES_SPILLED_REMOTE`.
5. **Candidate formulas**: `query_history.BYTES_SPILLED_TO_REMOTE_STORAGE > threshold`.
6. **Candidate thresholds**: Low: >1GB, Medium: >10GB, High: >50GB.
7. **Threshold type**: Absolute.
8. **Validation methodology**: Force memory exhaustion by executing massive `ORDER BY` operations on SF1000 data using an X-Small warehouse.
9. **False-positive risks**: Negligible. Any remote spill is definitively bad.
10. **Recommended severity model**: Tiered (Medium, High, Critical) based on bytes spilled.

## 2. LOCAL_SPILL
1. **Business impact**: Query slowdowns. Local SSD writes are faster than remote but much slower than RAM.
2. **Detection evidence**: `BYTES_SPILLED_TO_LOCAL_STORAGE`.
3. **Required telemetry sources**: `QUERY_HISTORY`.
4. **Required operator statistics fields**: `OPERATOR_ID`, `OPERATOR_TYPE`, `BYTES_SPILLED_LOCAL`.
5. **Candidate formulas**: `query_history.BYTES_SPILLED_TO_LOCAL_STORAGE > threshold`.
6. **Candidate thresholds**: Low: >5GB, Medium: >25GB, High: >100GB.
7. **Threshold type**: Absolute.
8. **Validation methodology**: Perform large hash joins on SF100 data with X-Small warehouses.
9. **False-positive risks**: Medium. Heavy ELT jobs may naturally spill to local disk without breaking SLAs.
10. **Recommended severity model**: Low to Medium.

## 3. FULL_TABLE_SCAN
1. **Business impact**: Excessive I/O and wasted compute cycles retrieving data that is mostly discarded.
2. **Detection evidence**: High `PARTITIONS_SCANNED` vs `PARTITIONS_TOTAL`.
3. **Required telemetry sources**: `QUERY_HISTORY`.
4. **Required operator statistics fields**: `OPERATOR_TYPE='TableScan'`, `RECORDS_SCANNED`, `RECORDS_PRODUCED`.
5. **Candidate formulas**: `(PARTITIONS_SCANNED / PARTITIONS_TOTAL) > 0.9` AND `PARTITIONS_TOTAL > min_partitions`.
6. **Candidate thresholds**: ratio > 0.95 AND total partitions > 10,000.
7. **Threshold type**: Relative (percentage) + Absolute floor.
8. **Validation methodology**: Select queries without `WHERE` clauses on massive fact tables.
9. **False-positive risks**: High. Legitimate massive aggregation queries (e.g., total revenue per year) require full scans.
10. **Recommended severity model**: Low (often used as enrichment rather than a primary alert).

## 4. POOR_PARTITION_PRUNING
1. **Business impact**: Similar to full table scans; scanning unnecessary micro-partitions due to un-clusterable filter predicates (like `LIKE '%...'` or functions on columns).
2. **Detection evidence**: Very high `PARTITIONS_SCANNED` but extremely low `RECORDS_PRODUCED` at the query level.
3. **Required telemetry sources**: `QUERY_HISTORY`.
4. **Required operator statistics fields**: `OPERATOR_TYPE='TableScan'`, `RECORDS_SCANNED`, `RECORDS_PRODUCED`.
5. **Candidate formulas**: `(PARTITIONS_SCANNED / PARTITIONS_TOTAL) > 0.5` AND `RECORDS_PRODUCED < 1000`.
6. **Candidate thresholds**: ratio > 0.5, rows returned < 1% of rows scanned.
7. **Threshold type**: Relative.
8. **Validation methodology**: Use a non-sargable predicate (e.g., `WHERE LOWER(name) = 'foo'`) on SF1000.
9. **False-positive risks**: Medium. Needle-in-a-haystack queries might inherently require large scans if the table lacks clustering.
10. **Recommended severity model**: Medium.

## 5. EXPENSIVE_JOIN
1. **Business impact**: Prolonged query execution due to massive row multiplication before filtering.
2. **Detection evidence**: An operator where `RECORDS_PRODUCED` exponentially exceeds the sum of `RECORDS_SCANNED` from inputs.
3. **Required telemetry sources**: `GET_QUERY_OPERATOR_STATS`.
4. **Required operator statistics fields**: `OPERATOR_TYPE='Join'`, `RECORDS_PRODUCED`, `EXECUTION_TIME_FRACTION`.
5. **Candidate formulas**: `operator.RECORDS_PRODUCED > (100 * sum(inputs.RECORDS_PRODUCED))`.
6. **Candidate thresholds**: Explosion factor > 100x.
7. **Threshold type**: Relative.
8. **Validation methodology**: Join two large tables on low-cardinality columns (e.g., boolean or status fields).
9. **False-positive risks**: Low. Massive row explosions are almost universally anti-patterns.
10. **Recommended severity model**: High.

## 6. CARTESIAN_JOIN
1. **Business impact**: Catastrophic query performance, often leading to OOM or query termination.
2. **Detection evidence**: Join operator with no equality predicates, producing cross-product row counts.
3. **Required telemetry sources**: `GET_QUERY_OPERATOR_STATS`.
4. **Required operator statistics fields**: `OPERATOR_TYPE='CartesianJoin'` (or equivalent), `RECORDS_PRODUCED`.
5. **Candidate formulas**: Operator type match AND `RECORDS_PRODUCED > 1_000_000`.
6. **Candidate thresholds**: > 1M rows produced from cartesian.
7. **Threshold type**: Absolute.
8. **Validation methodology**: Execute `SELECT * FROM lineitem, orders` on SF100.
9. **False-positive risks**: Low.
10. **Recommended severity model**: Critical.

## 7. LONG_RUNNING_QUERY
1. **Business impact**: Consumes cluster concurrency slots, potentially starving other queries. High credit cost.
2. **Detection evidence**: High `EXECUTION_TIME`.
3. **Required telemetry sources**: `QUERY_HISTORY`.
4. **Required operator statistics fields**: N/A (Handled at macro level).
5. **Candidate formulas**: `EXECUTION_TIME > threshold` OR `EXECUTION_TIME > (baseline_avg + 2*stddev)`.
6. **Candidate thresholds**: > 1 hour (Absolute) or > 3x historical average (Baseline).
7. **Threshold type**: Absolute or Baseline-driven.
8. **Validation methodology**: Inject `SYSTEM$WAIT(3600)`.
9. **False-positive risks**: High. Some jobs are expected to take hours. Baseline-driven approaches mitigate this.
10. **Recommended severity model**: Medium/High.

## 8. QUEUE_OVERLOAD
1. **Business impact**: Missed SLAs. Queries wait in queue because warehouse concurrency is maxed out.
2. **Detection evidence**: High `QUEUED_OVERLOAD_TIME`.
3. **Required telemetry sources**: `QUERY_HISTORY`, `WAREHOUSE_LOAD_HISTORY`.
4. **Required operator statistics fields**: N/A.
5. **Candidate formulas**: `QUEUED_OVERLOAD_TIME > threshold`.
6. **Candidate thresholds**: > 5 minutes.
7. **Threshold type**: Absolute.
8. **Validation methodology**: Submit 100 concurrent queries to an X-Small warehouse with no scaling.
9. **False-positive risks**: Low.
10. **Recommended severity model**: Medium.

## 9. QUEUE_PROVISIONING
1. **Business impact**: Minor delays (usually 1-3 seconds) while warehouse resumes or scales out.
2. **Detection evidence**: High `QUEUED_PROVISIONING_TIME`.
3. **Required telemetry sources**: `QUERY_HISTORY`.
4. **Required operator statistics fields**: N/A.
5. **Candidate formulas**: `QUEUED_PROVISIONING_TIME > threshold`.
6. **Candidate thresholds**: > 30 seconds.
7. **Threshold type**: Absolute.
8. **Validation methodology**: Query a suspended warehouse, measuring resume time.
9. **False-positive risks**: Medium. Provisioning delays are normal, only anomalous if sustained.
10. **Recommended severity model**: Low.

## 10. TRANSACTION_BLOCKING
1. **Business impact**: DML statements blocked waiting for locks held by other sessions.
2. **Detection evidence**: `TRANSACTION_BLOCKED_TIME`.
3. **Required telemetry sources**: `QUERY_HISTORY`.
4. **Required operator statistics fields**: N/A.
5. **Candidate formulas**: `TRANSACTION_BLOCKED_TIME > threshold`.
6. **Candidate thresholds**: > 60 seconds.
7. **Threshold type**: Absolute.
8. **Validation methodology**: Open transaction, update row, leave uncommitted. Update same row in session 2.
9. **False-positive risks**: Low. Sustained blocking is an operational incident.
10. **Recommended severity model**: High.

## 11. HIGH_NETWORK_SHUFFLE
1. **Business impact**: Slow execution due to excessive data movement between worker nodes.
2. **Detection evidence**: High network traffic in execution profile.
3. **Required telemetry sources**: `GET_QUERY_OPERATOR_STATS`.
4. **Required operator statistics fields**: `NETWORK_BYTES` or similar.
5. **Candidate formulas**: `NETWORK_BYTES > threshold`.
6. **Candidate thresholds**: > 500GB.
7. **Threshold type**: Absolute.
8. **Validation methodology**: Large aggregations grouped by high-cardinality keys on multi-node warehouses.
9. **False-positive risks**: Medium. Expected for massive aggregates.
10. **Recommended severity model**: Medium.

## 12. COST_ANOMALY
1. **Business impact**: Unexpected budget overrun.
2. **Detection evidence**: Spikes in `CREDITS_ATTRIBUTED_COMPUTE`.
3. **Required telemetry sources**: `QUERY_ATTRIBUTION_HISTORY`.
4. **Required operator statistics fields**: N/A.
5. **Candidate formulas**: `CREDITS_ATTRIBUTED_COMPUTE > (baseline_avg + 3*stddev)`.
6. **Candidate thresholds**: > 100 credits per query.
7. **Threshold type**: Baseline-driven & Absolute.
8. **Validation methodology**: Cross-join large tables on an X-Large warehouse to burn credits.
9. **False-positive risks**: Low. Large credit burns per query are almost always worth reviewing.
10. **Recommended severity model**: Critical.
