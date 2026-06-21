# Telemetry Validation & Assessment

This document serves as the foundation for implementing the Phase 2 Data Collection Layer. It outlines the accessibility, properties, and validation steps for the five V1 telemetry sources.

---

## 1. SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY

**Permissions Required:**
- `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database granted to `POV4_MONITOR_ROLE`.

**Validation Query:**
```sql
USE ROLE POV4_MONITOR_ROLE;
SELECT 
    QUERY_ID, WAREHOUSE_NAME, EXECUTION_TIME, QUEUED_OVERLOAD_TIME, 
    BYTES_SPILLED_TO_LOCAL_STORAGE, BYTES_SPILLED_TO_REMOTE_STORAGE, 
    PARTITIONS_SCANNED, PARTITIONS_TOTAL
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY 
WHERE START_TIME > DATEADD(day, -1, CURRENT_TIMESTAMP())
LIMIT 5;
```

**Important Columns to Inspect:**
- `EXECUTION_TIME`: Core metric for long-running queries.
- `QUEUED_OVERLOAD_TIME` / `QUEUED_PROVISIONING_TIME`: Indicates cluster contention or startup delays.
- `BYTES_SPILLED_TO_LOCAL_STORAGE` / `BYTES_SPILLED_TO_REMOTE_STORAGE`: Prime indicators of memory exhaustion.
- `PARTITIONS_SCANNED` / `PARTITIONS_TOTAL`: Used to calculate scan efficiency and identify missing clustering.

**Latency & Retention:**
- **Latency**: ~45 minutes.
- **Retention**: 1 year (365 days).

**Usefulness:**
- **Detection**: Extremely high. This is the primary driver for detecting spills, long-running queries, and queuing issues.
- **RCA**: High. Identifies the symptom (e.g., massive remote spill).
- **Recommendations**: Moderate. Indicates *what* needs fixing (e.g., "Reduce memory footprint").

---

## 2. SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY

**Permissions Required:**
- `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database granted to `POV4_MONITOR_ROLE`.

**Validation Query:**
```sql
USE ROLE POV4_MONITOR_ROLE;
SELECT 
    START_TIME, WAREHOUSE_NAME, AVG_RUNNING, AVG_QUEUED_LOAD, AVG_QUEUED_PROVISIONING
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_LOAD_HISTORY
WHERE START_TIME > DATEADD(day, -1, CURRENT_TIMESTAMP())
LIMIT 5;
```

**Important Columns to Inspect:**
- `AVG_RUNNING`: The average number of queries executing concurrently.
- `AVG_QUEUED_LOAD`: The average number of queries waiting because the warehouse is overloaded.
- `AVG_QUEUED_PROVISIONING`: The average number of queries waiting for a warehouse to resume/provision.

**Latency & Retention:**
- **Latency**: Up to 3 hours (though often faster).
- **Retention**: 1 year (365 days).

**Usefulness:**
- **Detection**: High. Identifies `WAREHOUSE_SATURATION` and `CONCURRENCY_BOTTLENECK`.
- **RCA**: High. Provides systemic context (e.g., "The query was slow because the warehouse was at maximum concurrency").
- **Recommendations**: High. Directly drives "Scale Out" (add clusters) vs "Scale Up" (increase T-Shirt size) recommendations.

---

## 3. SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY

**Permissions Required:**
- `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database granted to `POV4_MONITOR_ROLE`.

**Validation Query:**
```sql
USE ROLE POV4_MONITOR_ROLE;
SELECT 
    START_TIME, END_TIME, SERVICE_TYPE, NAME as WAREHOUSE_NAME, CREDITS_USED_COMPUTE
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY
WHERE START_TIME > DATEADD(day, -1, CURRENT_TIMESTAMP())
LIMIT 5;
```

**Important Columns to Inspect:**
- `CREDITS_USED_COMPUTE`: The actual compute cost incurred by a warehouse in a given hour.
- `SERVICE_TYPE`: Distinguishes between standard compute and serverless features.

**Latency & Retention:**
- **Latency**: 1 to 3 hours.
- **Retention**: 1 year (365 days).

**Usefulness:**
- **Detection**: Moderate. Useful for detecting macro `COST_ANOMALY` events across a whole warehouse.
- **RCA**: Low. It aggregates data hourly, meaning it lacks query-level granularity.
- **Recommendations**: Moderate. Highlights macro-level inefficient warehouses.

---

## 4. SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY

**Permissions Required:**
- `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database granted to `POV4_MONITOR_ROLE`.

**Validation Query:**
```sql
USE ROLE POV4_MONITOR_ROLE;
SELECT 
    QUERY_ID, WAREHOUSE_NAME, CREDITS_ATTRIBUTED_COMPUTE, START_TIME
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
WHERE START_TIME > DATEADD(day, -1, CURRENT_TIMESTAMP())
LIMIT 5;
```

**Important Columns to Inspect:**
- `CREDITS_ATTRIBUTED_COMPUTE`: The exact fraction of credits consumed by this specific query.

**Latency & Retention:**
- **Latency**: 1 to 24 hours (depending on account scale and Snowflake's internal processing).
- **Retention**: 1 year (365 days).

**Usefulness:**
- **Detection**: High. The only way to definitively detect a `HIGH_CREDIT_CONSUMPTION` query.
- **RCA**: Moderate. It doesn't explain *why* it was expensive, but it proves *that* it was expensive.
- **Recommendations**: High. Essential for FinOps prioritization. Recommendations can include ROI estimates based on actual historical credit consumption.

---

## 5. GET_QUERY_OPERATOR_STATS()

**Permissions Required:**
- `MONITOR` privilege on the specific warehouse (`POV4_WH` or the warehouse where the target query ran), or the `ACCOUNTADMIN` role.

**How to obtain a valid `query_id`:**
A valid `query_id` can be retrieved from `QUERY_HISTORY`.
```sql
SELECT QUERY_ID FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY WHERE EXECUTION_TIME > 10000 LIMIT 1;
```

**Validation Query:**
```sql
USE ROLE POV4_MONITOR_ROLE;
-- Replace <query_id> with the ID retrieved above
SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS('<query_id>'));
```

**Important Fields for Analysis:**
- **Remote Spill detection:**
  - Look for `BYTES_SPILLED_REMOTE` inside execution nodes like `Aggregate` or `Join`. It pinpoints exactly *which* step in the query plan ran out of memory.
- **Queue Wait analysis:**
  - *Not useful here.* The profile only covers execution time. Queue wait times happen *before* execution starts and must be diagnosed using `QUERY_HISTORY`.
- **Join analysis:**
  - Inspect `JOIN_TYPE` (e.g., INNER, LEFT OUTER).
  - Look for explosive `RECORDS_PRODUCED` compared to `RECORDS_SCANNED`.
  - Look for the `CARTESIAN` flag, which often indicates missing join keys and leads directly to massive memory consumption.
- **Cost analysis:**
  - `EXECUTION_TIME_FRACTION`: Identifies the most expensive node in the query plan. If an `Aggregate` node takes 85% of the execution time, the LLM RCA must focus strictly on that node.

**Latency & Retention:**
- **Latency**: Real-time. Available immediately after a query completes.
- **Retention**: 14 days. (This is why POV-4 must fetch it lazily but promptly).

**Usefulness:**
- **Detection**: Low. (Too expensive and slow to use for broad detection).
- **RCA**: Critical. This provides the execution tree required for the LLM to understand exactly why a query failed or spilled.
- **Recommendations**: Critical. The LLM needs the profile to recommend specific SQL rewrites (e.g., "Push down the filter before step 3 to reduce the dataset size entering the join").

---

## Validation Checklist

Use this checklist to track the validation exercise in your Snowflake environment.

| Telemetry Source | Accessible? (Yes/No) | Sample Row Retrieved? | Required Privs Confirmed? | Useful Columns Identified? | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `QUERY_HISTORY` | [ ] | [ ] | [ ] | [ ] | Validate `QUEUED_OVERLOAD_TIME` |
| `WAREHOUSE_LOAD_HISTORY` | [ ] | [ ] | [ ] | [ ] | Validate `AVG_QUEUED_LOAD` |
| `METERING_HISTORY` | [ ] | [ ] | [ ] | [ ] | Validate `CREDITS_USED_COMPUTE` |
| `QUERY_ATTRIBUTION_HISTORY`| [ ] | [ ] | [ ] | [ ] | Verify latency; it may be blank for recent queries. |
| `GET_QUERY_OPERATOR_STATS()` | [x] | [x] | [x] | [x] | Ensure target warehouse `MONITOR` priv is active. |
