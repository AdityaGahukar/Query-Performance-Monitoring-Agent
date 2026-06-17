# Issue-to-Telemetry Mapping

This document maps specific performance and cost issues detected by POV-4 to the underlying Snowflake telemetry sources required for Detection, Root Cause Analysis (RCA), and Recommendation generation.

## 1. REMOTE_SPILL
- **Detection Sources**: 
  - `QUERY_HISTORY` (Mandatory): `BYTES_SPILLED_TO_REMOTE_STORAGE` indicates the issue.
- **RCA Sources**: 
  - `QUERY_PROFILE` (Mandatory): Pinpoints the specific operator (e.g., massive Join or Sort) causing the spill.
  - `WAREHOUSE_LOAD_HISTORY` (Enrichment): Shows if the warehouse was heavily loaded, reducing available memory per query.
- **Recommendation Sources**: 
  - `QUERY_PROFILE` (Mandatory): Provides structural SQL rewrite hints.
  - `QUERY_ATTRIBUTION_HISTORY` (Enrichment): Calculates the financial cost of the spilling query to prioritize fixes.

## 2. LOCAL_SPILL
- **Detection Sources**: 
  - `QUERY_HISTORY` (Mandatory): `BYTES_SPILLED_TO_LOCAL_STORAGE`.
- **RCA Sources**: 
  - `QUERY_PROFILE` (Mandatory): Identifies the spilling node.
- **Recommendation Sources**: 
  - `QUERY_PROFILE` (Mandatory): Suggests filtering earlier in the plan or clustering.

## 3. LONG_RUNNING_QUERY
- **Detection Sources**: 
  - `QUERY_HISTORY` (Mandatory): `EXECUTION_TIME` exceeds thresholds.
- **RCA Sources**: 
  - `QUERY_PROFILE` (Mandatory): Reveals time spent (e.g., scanning vs joining).
- **Recommendation Sources**: 
  - `QUERY_PROFILE` (Mandatory): Identifies missing filters or inefficient joins.
  - `QUERY_ATTRIBUTION_HISTORY` (Enrichment): Prioritizes the finding based on compute cost.

## 4. QUEUE_WAIT
- **Detection Sources**: 
  - `QUERY_HISTORY` (Mandatory): `QUEUED_OVERLOAD_TIME` > threshold.
- **RCA Sources**: 
  - `WAREHOUSE_LOAD_HISTORY` (Mandatory): Confirms if the entire warehouse was saturated.
  - `WAREHOUSE_EVENTS_HISTORY` (Enrichment): Checks if the warehouse was suspended and simply took time to provision (cold start).
- **Recommendation Sources**: 
  - `WAREHOUSE_LOAD_HISTORY` (Mandatory): Recommends scaling out (multi-cluster) if queued load consistently outpaces running load.

## 5. WAREHOUSE_SATURATION
- **Detection Sources**: 
  - `WAREHOUSE_LOAD_HISTORY` (Mandatory): `AVG_RUNNING` hits the concurrency limit for the cluster size.
- **RCA Sources**: 
  - `QUERY_HISTORY` (Mandatory): Identifies the specific mix of queries running during the saturation period.
- **Recommendation Sources**: 
  - `WAREHOUSE_LOAD_HISTORY` (Mandatory): Suggests upgrading to a larger t-shirt size or increasing `MAX_CLUSTER_COUNT`.

## 6. HIGH_CREDIT_CONSUMPTION
- **Detection Sources**: 
  - `METERING_HISTORY` (Mandatory): Identifies a spike in total credits used across the account.
- **RCA Sources**: 
  - `WAREHOUSE_METERING_HISTORY` (Enrichment): Narrows the spike down to a specific warehouse.
  - `QUERY_ATTRIBUTION_HISTORY` (Mandatory): Narrows the spike down to specific queries.
- **Recommendation Sources**: 
  - `QUERY_ATTRIBUTION_HISTORY` (Mandatory): Recommends optimizing the top N most expensive queries.

## 7. COST_ANOMALY
- **Detection Sources**: 
  - `METERING_HISTORY` (Mandatory): Identifies unexpected credit burn over a time window.
- **RCA Sources**: 
  - `RESOURCE_MONITORS` (Enrichment): Identifies if the anomaly is approaching a hard budget limit.
  - `WAREHOUSE_METERING_HISTORY` (Mandatory): Attributes anomaly to a warehouse.
- **Recommendation Sources**: 
  - `WAREHOUSE_EVENTS_HISTORY` (Enrichment): Recommends reducing `AUTO_SUSPEND` if warehouses are left running idle.

## 8. PROVISIONING_DELAY
- **Detection Sources**: 
  - `QUERY_HISTORY` (Mandatory): `QUEUED_PROVISIONING_TIME` is high.
- **RCA Sources**: 
  - `WAREHOUSE_EVENTS_HISTORY` (Mandatory): Correlates with a RESUME event.
- **Recommendation Sources**: 
  - `WAREHOUSE_EVENTS_HISTORY` (Mandatory): Suggests leaving the warehouse running longer (increasing `AUTO_SUSPEND`) if frequent cold starts are occurring.

## 9. CONCURRENCY_BOTTLENECK
- **Detection Sources**: 
  - `WAREHOUSE_LOAD_HISTORY` (Mandatory): High `AVG_QUEUED_LOAD` while `AVG_RUNNING` is at capacity.
- **RCA Sources**: 
  - `QUERY_HISTORY` (Mandatory): Evaluates if many small queries are piling up.
- **Recommendation Sources**: 
  - `WAREHOUSE_LOAD_HISTORY` (Mandatory): Suggests scaling out (increasing maximum clusters in a multi-cluster warehouse) rather than scaling up.
