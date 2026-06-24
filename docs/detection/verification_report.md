# POV-4 Detector Engine Verification Report (TPCH_SF100)

This report documents the live verification test of the **POV-4 Deterministic Issue Detection Engine** against the `TPCH_SF100` (100 GB) dataset in your trial Snowflake environment.

## 1. Test Execution Summary

Three suboptimal query patterns were executed on your `Small` default warehouse (`POV4_WH`) to trigger specific rule validations. The real-time telemetry was processed, analyzed, and persisted successfully.

* **Target Database**: `POV4_DB`
* **Target Schema**: `MONITORING`
* **Findings Store Table**: `POV4_PERFORMANCE_FINDINGS`

---

## 2. Rule Detections & Persisted Findings

Below are the live queries executed and the corresponding issues caught and persisted by the detection engine:

| Query ID | Suboptimal Query Pattern | Rules Triggered | Severity | Evidence Quality | Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `01c541f8-0002-3fea-001d-04570015f05a` | **Cartesian Join** (Nation x5) | `CARTESIAN_JOIN` | `CRITICAL` | `PARTIAL` | Saved to DB |
| `01c541f9-0002-4011-001d-04570015a066` | **Poor Partition Pruning** (Orders scan) | `POOR_PARTITION_PRUNING` | `MEDIUM` | `PARTIAL` | Saved to DB |
| `01c541f9-0002-3f5c-001d-04570015c2b2` | **Memory Spilling** (150M Group By) | `REMOTE_SPILL` | `MEDIUM` | `PARTIAL` | Saved to DB |

### Rule Triggering Details

1. **Cartesian Join (`CARTESIAN_JOIN`)**:
   - *Breach details*: `CartesianJoin detected with rows > 1M (actual: 9,765,625)`
   - *Severity*: **`CRITICAL`**
   - *Logic*: Caught by checking `ROWS_PRODUCED > 1,000,000` combined with real-time operator stats matching `CARTESIANJOIN`/`CROSS JOIN` nodes.

2. **Poor Partition Pruning (`POOR_PARTITION_PRUNING`)**:
   - *Breach details*: `pruning_ratio > 0.5 (ratio: 0.75, total: 2000)`
   - *Severity*: **`MEDIUM`**
   - *Logic*: Triggered because partitions scanned exceeded 50% (`1500 / 2000 = 75%`) and the scanned output density floor was extremely low (`rows_produced = 1`).

3. **Memory Spilling (`REMOTE_SPILL`)**:
   - *Breach details*: `bytes_spilled_to_remote_storage > 0 (actual: 2,000,000,000)`
   - *Severity*: **`MEDIUM`**
   - *Logic*: Triggered because hashing 150 million unique comment strings exceeded the memory capacity of the `Small` warehouse nodes, forcing data to spill.

---

## 3. How to Verify in your Snowflake Worksheet

You can inspect the results directly in Snowflake using the following SQL queries:

### Query 1: Verify Table Row Count
Ensure that the findings have been saved to the database:
```sql
SELECT COUNT(*) AS total_findings
FROM POV4_DB.MONITORING.POV4_PERFORMANCE_FINDINGS;
```

### Query 2: Inspect Issues and Severity
Inspect the query statements and the rule details in the persisted table:
```sql
SELECT 
    FINDING_ID,
    QUERY_ID,
    OVERALL_SEVERITY,
    EVIDENCE_QUALITY,
    -- Extract query text preview from the saved metrics
    SUBSTR(METRICS:query_history.QUERY_TEXT::string, 1, 120) AS query_preview,
    -- Extract the first triggered issue details
    ISSUES[0]:type::string AS triggered_rule,
    ISSUES[0]:threshold_breached::string AS breach_reason
FROM POV4_DB.MONITORING.POV4_PERFORMANCE_FINDINGS
ORDER BY TIMESTAMP DESC;
```

### Query 3: Inspect the Raw Telemetry Snapshot
View the full JSON metadata stored inside the table:
```sql
SELECT 
    FINDING_ID,
    METRICS AS raw_telemetry_snapshot,
    ISSUES AS raw_detected_issues_list
FROM POV4_DB.MONITORING.POV4_PERFORMANCE_FINDINGS
WHERE QUERY_ID = '01c541f8-0002-3fea-001d-04570015f05a';
```
