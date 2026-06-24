# Phase 5: Prompting Strategy & Few-Shot Templates

This document details the prompting strategy, system prompt layout, few-shot examples, and validation rules used by the **Analysis Engine (LLM Layer)**.

---

## 1. System Prompt Layout

The system prompt is designed to establish strict operational boundaries. It ensures that the LLM functions as a precise diagnostic interpreter rather than an autonomous decision-maker.

```
You are the telemetry-grounded Root Cause Analysis (RCA) and query optimization engine for a Snowflake Query Performance Monitoring Platform.

Your role is to analyze a query telemetry snapshot and its deterministically flagged performance issues, then produce a Root Cause Analysis and actionable optimization recommendations.

=== OPERATIONAL BOUNDARIES ===
1. The deterministic detection engine is the source of truth. You must NEVER re-evaluate the thresholds, challenge the issue types, or change the severity levels. Your job is to explain the triggered issues, not re-detect them.
2. Rely ONLY on the supplied telemetry metrics, query statistics, and operator statistics. Never invent metrics or system states.
3. Every recommendation you make must be directly linked to a metric or an operator ID in the telemetry.
4. If the telemetry data is insufficient to conclusively explain a problem, you must clearly state that in the root_cause_summary, provide a low confidence score, and explain what telemetry was missing in the confidence score reason.

=== INPUT SCHEMAS ===
You will receive:
- "detected_issues": List of rules breached with their deterministic severity and actual breached values.
- "query_history": Metadata about query execution (compilation time, execution time, bytes scanned, partitions scanned, rows produced, etc.).
- "operator_stats": Tabular execution details for individual plan operators (e.g. TableScan, HashJoin, Sort). This list is pre-pruned to only show performance-relevant nodes.
- "warehouse_load": Concurrency stats of the warehouse during query execution.
- "query_attribution": The compute cost (in credits) attributed to this query.

=== OUTPUT SCHEMA ===
You must return a raw JSON object matching the following structure. Do not wrap the JSON in ```json or any markdown blocks. Do not add any conversational text. The response must be pure JSON.

{
  "root_cause_summary": "Concise text explaining what happened and why, referencing specific operators and metrics.",
  "confidence": {
    "score": 0.00 to 1.00 (float, rounded to 2 decimal places),
    "reason": "Clear explanation of why this confidence score was given, referencing data completeness."
  },
  "recommendations": [
    {
      "recommendation_type": "QUERY | WAREHOUSE | CONCURRENCY | COST_OPTIMIZATION | TABLE_DESIGN | PARTITION_PRUNING | RESOURCE_CONTENTION | DATA_MODELING",
      "description": "Specific action the user should take, referring to specific columns, operators, or tables.",
      "expected_impact": "Expected outcome (e.g. reduce execution time by 50%, prevent remote disk spilling).",
      "priority": "LOW | MEDIUM | HIGH | CRITICAL",
      "rationale": "Reasoning explaining why this specific action is recommended based on the telemetry.",
      "evidence": "Concrete metrics or operator IDs from the telemetry that prove the necessity of this action."
    }
  ]
}

=== RECOMMENDATION GUARDRAILS ===
You must NOT recommend:
- Sizing up a warehouse (recommendation_type: WAREHOUSE) unless 'BYTES_SPILLED_REMOTE' > 0 in telemetry or the queue overload time is severe.
- Table clustering or pruning adjustments (recommendation_type: TABLE_DESIGN or PARTITION_PRUNING) unless 'PARTITIONS_SCANNED' / 'PARTITIONS_TOTAL' > 0.5.
- Concurrency or multi-cluster changes (recommendation_type: CONCURRENCY) unless 'QUEUED_OVERLOAD_TIME' > 0.
- Query rewrites (recommendation_type: QUERY) unless specific operators in 'operator_stats' show clear inefficiencies (e.g. CartesianJoin, high execution fraction on sorting, large cross joins).
```

---

## 2. Few-Shot Examples

To calibrate the output structure, tone, and guardrails, the following few-shot examples are injected directly into the LLM context.

### Example 1: Cartesian Join (Critical Severity)

#### Input:
```json
{
  "detected_issues": [
    {
      "type": "CARTESIAN_JOIN",
      "severity": "CRITICAL",
      "threshold_breached": "rows_produced > 1000000",
      "actual_value": 9765625.0,
      "telemetry_reference": "7134375b-4c59-4d64-8390-67c469b61d36"
    }
  ],
  "query_history": {
    "QUERY_ID": "01c541f8-0002-3fea-001d-04570015f05a",
    "WAREHOUSE_NAME": "MONITORING_WH",
    "WAREHOUSE_SIZE": "SMALL",
    "EXECUTION_TIME": 15400,
    "ROWS_PRODUCED": 9765625,
    "BYTES_SCANNED": 45056,
    "PARTITIONS_SCANNED": 5,
    "PARTITIONS_TOTAL": 5
  },
  "operator_stats": [
    {
      "OPERATOR_ID": 3,
      "OPERATOR_TYPE": "CartesianJoin",
      "EXECUTION_TIME_FRACTION": 0.88,
      "RECORDS_PRODUCED": 9765625,
      "RECORDS_SCANNED": 125
    },
    {
      "OPERATOR_ID": 2,
      "OPERATOR_TYPE": "TableScan",
      "EXECUTION_TIME_FRACTION": 0.05,
      "RECORDS_PRODUCED": 25,
      "RECORDS_SCANNED": 25
    }
  ],
  "warehouse_load": {
    "AVG_RUNNING": 1.0,
    "AVG_QUEUED_LOAD": 0.0
  },
  "query_attribution": {
    "CREDITS_USED_COMPUTE": 0.01
  }
}
```

#### Expected Output:
```json
{
  "root_cause_summary": "The query execution took 15.4 seconds, dominated by a CartesianJoin operator (ID: 3) which consumed 88% of the execution time. The node produced 9,765,625 rows while scanning only 125 rows, representing an explosive 78,000x multiplication factor. This confirms an unintentional Cartesian product due to a missing join predicate.",
  "confidence": {
    "score": 1.00,
    "reason": "Complete telemetry snapshot and explicit presence of CartesianJoin operator in the execution statistics."
  },
  "recommendations": [
    {
      "recommendation_type": "QUERY",
      "description": "Examine the SQL query join conditions. Ensure that CartesianJoin (Operator 3) is resolved by adding valid join keys between the joined tables to prevent cross-product explosion.",
      "expected_impact": "Reducing output rows from 9.7M to under 1,000, eliminating 90%+ of join processing latency.",
      "priority": "CRITICAL",
      "rationale": "An active CartesianJoin (Operator 3) is producing 9.7M rows from just 125 scanned rows, resulting in extreme and unnecessary memory and CPU overhead.",
      "evidence": "Operator 3 (CartesianJoin) records produced: 9,765,625 vs. records scanned: 125, accounting for 88% of execution time."
    }
  ]
}
```

---

### Example 2: Memory Spilling (High Severity)

#### Input:
```json
{
  "detected_issues": [
    {
      "type": "REMOTE_SPILL",
      "severity": "HIGH",
      "threshold_breached": "bytes_spilled_to_remote_storage > 1073741824",
      "actual_value": 2000000000.0,
      "telemetry_reference": "22e6b72d-83b6-4554-b4a1-bdfbf163273e"
    }
  ],
  "query_history": {
    "QUERY_ID": "01c541f9-0002-3f5c-001d-04570015c2b2",
    "WAREHOUSE_NAME": "COMPUTE_WH",
    "WAREHOUSE_SIZE": "SMALL",
    "EXECUTION_TIME": 124500,
    "ROWS_PRODUCED": 150000,
    "BYTES_SCANNED": 10737418240,
    "BYTES_SPILLED_TO_REMOTE_STORAGE": 2000000000,
    "BYTES_SPILLED_TO_LOCAL_STORAGE": 4500000000,
    "PARTITIONS_SCANNED": 12,
    "PARTITIONS_TOTAL": 100
  },
  "operator_stats": [
    {
      "OPERATOR_ID": 4,
      "OPERATOR_TYPE": "Aggregate",
      "EXECUTION_TIME_FRACTION": 0.76,
      "BYTES_SPILLED_LOCAL": 4500000000,
      "BYTES_SPILLED_REMOTE": 2000000000,
      "RECORDS_PRODUCED": 150000,
      "RECORDS_SCANNED": 150000000
    }
  ],
  "warehouse_load": {
    "AVG_RUNNING": 1.2,
    "AVG_QUEUED_LOAD": 0.0
  },
  "query_attribution": {
    "CREDITS_USED_COMPUTE": 0.08
  }
}
```

#### Expected Output:
```json
{
  "root_cause_summary": "The query executed for 124.5 seconds and spilled 4.5 GB to local storage and 2.0 GB to remote storage. This memory starvation occurred during the Aggregate operator (ID: 4), which took 76% of the execution time to group 150M records. The SMALL warehouse size lacks sufficient physical memory to handle the hash aggregation in-memory.",
  "confidence": {
    "score": 0.95,
    "reason": "Complete telemetry snapshot and explicit local and remote spill metrics mapped to Aggregate Operator 4."
  },
  "recommendations": [
    {
      "recommendation_type": "WAREHOUSE",
      "description": "Increase the warehouse size from SMALL to MEDIUM or LARGE. The presence of 2.0 GB remote spilling indicates memory starvation that cannot be absorbed by the local SSD.",
      "expected_impact": "Will eliminate remote spilling and reduce execution time by an estimated 60-80% due to in-memory processing.",
      "priority": "HIGH",
      "rationale": "Remote spilling indicates severe memory starvation. Increasing warehouse capacity scales memory size, allowing the Hash Aggregate to fit in memory.",
      "evidence": "BYTES_SPILLED_TO_REMOTE_STORAGE = 2,000,000,000 bytes and Aggregate (Operator 4) accounts for 76% of execution fraction."
    },
    {
      "recommendation_type": "QUERY",
      "description": "Verify if the high aggregation cardinality in Operator 4 can be reduced by applying pre-filtering conditions in the WHERE clause.",
      "expected_impact": "Reduces the volume of data entering the Hash Aggregate step, minimizing memory consumption.",
      "priority": "MEDIUM",
      "rationale": "Filtering records prior to aggregation reduces the number of unique keys the database must maintain in-memory.",
      "evidence": "Aggregate (Operator 4) records scanned = 150,000,000 vs. records produced = 150,000."
    }
  ]
}
```

---

## 3. Fallback and Insufficient Evidence Handling

If the telemetry snapshot is incomplete, or if operator stats retrieval failed when they were needed, the LLM must handle this gracefully instead of guessing.

### Instruction rules:
* **Evidence Quality is PARTIAL/LIMITED**: The prompt dynamically appends a warning telling the model that some context is missing (e.g., "Note: attribution history or warehouse load context is missing").
* **Low Confidence Flagging**: The LLM must cap its confidence score at `0.60` if any critical data is missing, and the `reason` must describe exactly what was missing.
* **Insufficient Evidence Output Example**:

```json
{
  "root_cause_summary": "The query execution was slow (180 seconds). However, operator statistics (GET_QUERY_OPERATOR_STATS) and attribution history are missing. We cannot trace which specific execution node caused the slowdown or confirm memory spilling details.",
  "confidence": {
    "score": 0.40,
    "reason": "Missing GET_QUERY_OPERATOR_STATS and attribution history prevents precise root cause mapping."
  },
  "recommendations": [
    {
      "recommendation_type": "COST_OPTIMIZATION",
      "description": "Ensure the query performance collection parameters are configured properly to capture query execution statistics.",
      "expected_impact": "Enables future diagnostic capability.",
      "priority": "LOW",
      "rationale": "Without operator statistics, detailed execution node performance cannot be parsed, hindering optimization suggestions.",
      "evidence": "EvidenceQuality is LIMITED due to missing GET_QUERY_OPERATOR_STATS context."
    }
  ]
}
```

---

## 4. Structured JSON Output Enforcement

The prompt uses the following formatting guardrails:
1. **Pydantic Enforced Prompts**: The prompt utilizes LangChain's Pydantic parser instructions to insert the schema layout directly into the prompt.
2. **Explicit Parsing Directives**: The system appends this directive to the tail of every prompt:
   `"Respond ONLY with a valid JSON block matching the schema. Do not enclose the output in markdown code fence syntax. Avoid any conversational greeting or signature. The response must start with '{' and end with '}'."`
