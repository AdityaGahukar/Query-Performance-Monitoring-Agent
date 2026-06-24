# Telemetry Source Assessment

This document evaluates available Snowflake telemetry sources for POV-4, classifying them based on implementation phases, and outlines a comprehensive telemetry strategy.

## Evaluated Telemetry Sources

### 1. QUERY_HISTORY
1. **Description**: Contains execution statistics, SQL text, and metadata for queries executed in the account. Accessible via `ACCOUNT_USAGE` and `INFORMATION_SCHEMA`.
2. **Key fields available**: `QUERY_ID`, `QUERY_TEXT`, `WAREHOUSE_NAME`, `EXECUTION_TIME`, `QUEUED_OVERLOAD_TIME`, `BYTES_SPILLED_TO_LOCAL_STORAGE`, `BYTES_SPILLED_TO_REMOTE_STORAGE`, `PARTITIONS_SCANNED`.
3. **Detection use cases**: Identifying long-running queries, remote/local spills, queue waits, and full table scans.
4. **RCA use cases**: Analyzing `QUERY_TEXT` to identify poorly written joins or lack of filtering. Checking `PARTITIONS_SCANNED` vs `PARTITIONS_TOTAL`.
5. **Recommendation use cases**: Proposing SQL rewrites, scaling warehouses.
6. **Benefits**: The most critical and granular view of individual workload performance.
7. **Limitations**: High data volume; `ACCOUNT_USAGE` latency (up to 45 mins) can delay alerts if not using `INFORMATION_SCHEMA`.
8. **Data volume considerations**: Extremely high. Must filter by thresholds.
9. **Collection frequency considerations**: High (every 5-15 minutes using `INFORMATION_SCHEMA`).

### 2. WAREHOUSE_LOAD_HISTORY
1. **Description**: Shows historical average load on warehouses, broken down by running and queued queries.
2. **Key fields available**: `START_TIME`, `END_TIME`, `WAREHOUSE_NAME`, `AVG_RUNNING`, `AVG_QUEUED_LOAD`, `AVG_QUEUED_PROVISIONING`.
3. **Detection use cases**: Detecting warehouse saturation and concurrency bottlenecks.
4. **RCA use cases**: Determining if a specific query was slow due to an overloaded warehouse (systemic issue) rather than its own SQL complexity.
5. **Recommendation use cases**: Recommending Multi-Cluster Warehouses (scaling out) or sizing up.
6. **Benefits**: Perfect for systemic concurrency analysis rather than individual query tuning.
7. **Limitations**: Aggregated metrics; doesn't point to specific queries.
8. **Data volume considerations**: Low to Medium.
9. **Collection frequency considerations**: Medium (every 15-30 minutes).

### 3. GET_QUERY_OPERATOR_STATS (Operator Stats)
1. **Description**: Provides tabular execution statistics for individual query operators via GET_QUERY_OPERATOR_STATS.
2. **Key fields available**: `OPERATOR_ID`, `OPERATOR_TYPE`, `EXECUTION_TIME_FRACTION`, `BYTES_SPILLED_LOCAL`, `BYTES_SPILLED_REMOTE`.
3. **Detection use cases**: Typically used after detection for deep inspection.
4. **RCA use cases**: Identifying exactly which step caused a spill or took the most time.
5. **Recommendation use cases**: Highly precise SQL rewrite recommendations based on failing nodes.
6. **Benefits**: Provides execution metrics essential for the LLM Analysis Agent. Flattened tabular structure is easier to parse than a raw execution tree.
7. **Limitations**: Very expensive to collect for all queries. Must be fetched on-demand. Lacks the visual tree layout of the web UI, requiring the LLM to reconstruct context from parent/child IDs if needed.
8. **Data volume considerations**: Very high per query. 
9. **Collection frequency considerations**: On-demand only (triggered by Issue Detection).

### 4. METERING_HISTORY
1. **Description**: Hourly credit usage for compute resources across the account.
2. **Key fields available**: `START_TIME`, `END_TIME`, `ENTITY_ID`, `NAME`, `CREDITS_USED_COMPUTE`.
3. **Detection use cases**: Detecting sudden spikes in overall credit consumption (cost anomalies).
4. **RCA use cases**: Correlating high costs with workload surges or inefficiently sized warehouses.
5. **Recommendation use cases**: Recommending down-sizing during off-peak hours.
6. **Benefits**: Directly ties performance monitoring to financial impact (FinOps).
7. **Limitations**: Hourly granularity only.
8. **Data volume considerations**: Low.
9. **Collection frequency considerations**: Hourly.

### 5. QUERY_ATTRIBUTION_HISTORY
1. **Description**: Maps compute cost back to the specific query level.
2. **Key fields available**: `QUERY_ID`, `CREDITS_ATTRIBUTED`.
3. **Detection use cases**: Flagging the most expensive individual queries.
4. **RCA use cases**: Enhancing severity of findings based on direct financial cost.
5. **Recommendation use cases**: Essential for prioritizing ROI of optimization opportunities.
6. **Benefits**: True unit economics for workloads. Answers "Which problematic queries are the most expensive?".
7. **Limitations**: Heavy view, often lags `QUERY_HISTORY`.
8. **Data volume considerations**: High.
9. **Collection frequency considerations**: Daily or Hourly batch.

### 6. WAREHOUSE_METERING_HISTORY
1. **Description**: Hourly credit usage specifically broken down by warehouse.
2. **Key fields available**: `START_TIME`, `END_TIME`, `WAREHOUSE_NAME`, `CREDITS_USED_COMPUTE`, `CREDITS_USED_CLOUD_SERVICES`.
3. **Detection use cases**: Detecting warehouse-specific cost anomalies and over-provisioning.
4. **RCA use cases**: Identifying which warehouse is driving cost spikes.
5. **Recommendation use cases**: Tuning auto-suspend or adjusting warehouse sizing.
6. **Benefits**: Pinpoints FinOps issues to specific compute clusters.
7. **Limitations**: Hourly granularity.
8. **Data volume considerations**: Low.
9. **Collection frequency considerations**: Hourly.

#### Cost Telemetry Comparison Roles
- **`METERING_HISTORY`**: Provides account-level or top-level resource cost tracking. Role: Macro-level cost anomaly detection.
- **`WAREHOUSE_METERING_HISTORY`**: Provides compute cluster-level costs. Role: Identifies which specific warehouse is inefficient, informing infrastructure sizing recommendations.
- **`QUERY_ATTRIBUTION_HISTORY`**: Provides query-level costs. Role: Pinpoints exact query ROI, determining which specific finding should be prioritized first.

### 7. TABLE_STORAGE_METRICS
1. **Description**: Detailed metrics on table sizes, micro-partitions, and clustering depth.
2. **Key fields available**: `TABLE_NAME`, `ACTIVE_BYTES`, `CLONE_BYTES`, `FAILSAFE_BYTES`.
3. **Detection use cases**: Detecting large unclustered tables or tables with excessive fail-safe overhead.
4. **RCA use cases**: Diagnosing poor partition pruning in `QUERY_HISTORY` by cross-referencing table cluster health.
5. **Recommendation use cases**: Recommending automatic clustering, cluster key selection.
6. **Benefits**: Essential for storage and partition pruning RCA.
7. **Limitations**: Can be slow to query across large accounts.
8. **Data volume considerations**: Medium.
9. **Collection frequency considerations**: Daily.

### 8. WAREHOUSE_EVENTS_HISTORY
1. **Description**: Tracks cluster scaling events, warehouse suspensions, and resumptions.
2. **Key fields available**: `TIMESTAMP`, `WAREHOUSE_NAME`, `EVENT_NAME`, `EVENT_REASON`.
3. **Detection use cases**: Detecting warehouse thrashing (frequent start/stop cycles).
4. **RCA use cases**: Explaining query latency due to "warehouse resume/provisioning" time.
5. **Recommendation use cases**: Tuning `AUTO_SUSPEND` intervals.
6. **Benefits**: Explains "cold start" latency.
7. **Limitations**: Doesn't track query-level data.
8. **Data volume considerations**: Low.
9. **Collection frequency considerations**: Hourly.

### 9. RESOURCE_MONITORS
1. **Description**: Alerts and limits on credit consumption at the account or warehouse level.
2. **Key fields available**: `CREDIT_QUOTA`, `USED_CREDITS`, `LEVEL`.
3. **Detection use cases**: Budget threshold breaches.
4. **RCA use cases**: Explaining warehouse throttling or suspension scenarios due to budget limits.
5. **Recommendation use cases**: Adjusting quotas or isolating workloads.
6. **Benefits**: Contextualizes system-imposed limits.
7. **Limitations**: Does not provide performance details.
8. **Data volume considerations**: Very Low.
9. **Collection frequency considerations**: Daily / Event-driven.

### 10. TASK_HISTORY & SERVERLESS_TASK_HISTORY
1. **Description**: Execution records for Snowflake tasks.
2. **Key fields available**: `TASK_NAME`, `STATE`.
3. **Detection use cases**: Detecting failed tasks.
4. **RCA use cases**: Checking if overlapping tasks caused warehouse queuing.
5. **Recommendation use cases**: Rescheduling tasks.
6. **Benefits**: Specialized for orchestration.
7. **Limitations**: Only covers scheduled tasks.
8. **Data volume considerations**: Medium.
9. **Collection frequency considerations**: Medium.

### 11. DATABASE_STORAGE_USAGE_HISTORY
1. **Description**: High-level storage usage per database.
2. **Key fields available**: `DATABASE_NAME`, `AVERAGE_DATABASE_BYTES`.
3. **Benefits**: Storage cost monitoring.
4. **Limitations**: Too high-level for query RCA.

### 12. ACCESS_HISTORY
1. **Description**: Audit log of objects accessed and data written.
2. **Key fields available**: `QUERY_ID`, `BASE_OBJECTS_ACCESSED`.
3. **Benefits**: Great for data lifecycle.
4. **Limitations**: Very complex JSON structures to parse.

---

## Telemetry Value Matrix

| Telemetry Source | Detection Value | RCA Value | Recommendation Value | Priority | Justification |
|------------------|----------------|-----------|----------------------|----------|---------------|
| **`QUERY_HISTORY`** | Very High | High | Medium | **V1** | Primary source for individual query bottlenecks. |
| **`GET_QUERY_OPERATOR_STATS`** | Low | Very High | Very High | **V1** | Tabular operator statistics essential for LLM RCA and rewrites. |
| **`WAREHOUSE_LOAD_HISTORY`** | High | High | Medium | **V1** | Crucial for system-wide queuing and concurrency bottlenecks. |
| **`METERING_HISTORY`** | High | Medium | Low | **V1** | Needed to address the core business problem of cost overruns. |
| **`QUERY_ATTRIBUTION_HISTORY`** | Medium | Medium | Very High | **V1** | Enables high-ROI prioritization of optimization findings. |
| **`WAREHOUSE_METERING_HISTORY`**| High | Medium | Medium | **V1.5** | Adds warehouse-level cost context. |
| **`WAREHOUSE_EVENTS_HISTORY`** | Medium | Medium | High | **V1.5** | Essential for cold-start latency RCA and auto-suspend tuning. |
| **`RESOURCE_MONITORS`** | Medium | High | Medium | **V1.5** | Contextualizes throttling and budget constraints. |
| **`TABLE_STORAGE_METRICS`** | Medium | High | High | **V2+** | Storage optimizations are valuable but secondary to V1 query tuning. |
| **`TASK_HISTORY`** | Medium | Low | Medium | **V2+** | Pipeline specific, out of scope for initial core engine. |
| **`ACCESS_HISTORY`** | Low | Medium | Medium | **V2+** | Useful for deprecating unused assets, not core query tuning. |

---

## Classification & Final V1 Telemetry Strategy

### Must Have (V1 - Core Performance & FinOps Engine)
- **`QUERY_HISTORY`**: The fundamental source for query bottlenecks.
- **`WAREHOUSE_LOAD_HISTORY`**: Provides systemic concurrency context.
- **`GET_QUERY_OPERATOR_STATS`**: The deepest RCA source for the LLM.
- **`METERING_HISTORY`**: Fulfills the core business requirement to detect cost overruns.
- **`QUERY_ATTRIBUTION_HISTORY`**: Identifies which problematic queries are the most expensive and ensures POV-4 outputs findings prioritized by optimization ROI.

### Good To Have (V1.5 - Operational Context)
- **`WAREHOUSE_METERING_HISTORY`**: Adds warehouse-level finops context.
- **`WAREHOUSE_EVENTS_HISTORY`**: Tunes `AUTO_SUSPEND` and diagnoses cold starts.
- **`RESOURCE_MONITORS`**: Provides context on credit limits, budget breaches, and system throttling.

### Future Phase (V2+ - Storage & Holistic Observability)
- **`TABLE_STORAGE_METRICS`**: Pushed to V2 since V1 RCA can leverage `QUERY_HISTORY` and `GET_QUERY_OPERATOR_STATS` for initial query tuning without requiring deep storage telemetry.
- **`TASK_HISTORY`**, **`ACCESS_HISTORY`**, **`DATABASE_STORAGE_USAGE_HISTORY`**: Deferred as they focus on pipelines, lifecycle management, and storage rather than immediate compute performance.

### V1 Strategy Rationale
The V1 strategy marries **Performance Detection** with **FinOps Prioritization**. By promoting `METERING_HISTORY` and `QUERY_ATTRIBUTION_HISTORY` to V1, POV-4 not only finds slow queries but explicitly ranks them by financial impact. This ensures that downstream agents (POV-3) and human operators tackle the highest ROI issues first. We deliberately defer storage metrics (`TABLE_STORAGE_METRICS`) to keep the initial LLM context window focused purely on compute and execution plans, reducing complexity while solving the immediate business problems of slow queries and compute cost overruns.
