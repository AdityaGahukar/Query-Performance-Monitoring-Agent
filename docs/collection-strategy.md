# Collection Strategy

This document outlines the telemetry ingestion mechanics for POV-4 to satisfy the V1 strategy.

## 1. Telemetry Collection Architecture
- **Primary Source**: `INFORMATION_SCHEMA` for near real-time detection of query bottlenecks.
- **Enrichment Source**: `ACCOUNT_USAGE` for cost attribution, metering, and load history.
- **Execution Mechanism**: Background task runner continuously executing Snowflake Python connector queries.

## 2. Polling Frequencies
- `QUERY_HISTORY` (via `INFORMATION_SCHEMA`): Every 5 minutes.
- `WAREHOUSE_LOAD_HISTORY`: Every 15 minutes.
- `METERING_HISTORY` / `WAREHOUSE_METERING_HISTORY`: Hourly.
- `QUERY_ATTRIBUTION_HISTORY`: Hourly.

## 3. Watermark Strategy
To ensure Exactly-Once processing and prevent alert duplication:
- **State Store**: A lightweight DB table (`pov4_watermarks`) tracks `last_processed_timestamp` per telemetry view.
- **Query Filter**: Each polling cycle appends `WHERE END_TIME > $watermark` and `END_TIME <= $current_cycle_end`.
- **Update**: The watermark is advanced and committed only after the telemetry batch is successfully persisted.

## 4. Query Profile Retrieval Strategy
Profiles are massive and cannot be synced universally.
- **On-Demand Only**: `SYSTEM$GET_QUERY_PROFILE(query_id)` is invoked *only* if the Detection Engine flags a specific query with an issue.
- **Pruning**: Only the heaviest operators (top N by `EXECUTION_TIME_FRACTION`) and failing nodes are extracted and injected into the LLM prompt to save token context limits.

## 5. Failure Recovery Strategy
- **Snowflake API Unavailability**: Utilize an exponential backoff retry loop. The watermark ensures no telemetry is skipped once the connection restores.
- **Missing Enrichment Data (Lag)**: If `QUERY_ATTRIBUTION_HISTORY` is delayed (due to Snowflake internal lag), the system will process the finding with `credits_attributed=null`, deduct points from the `confidence_score`, and proceed rather than halting the pipeline.
- **Dead-Letter Processing**: If a finding fails during aggregation or analysis, the raw `TelemetrySnapshot` is stored in a Dead Letter Queue (DLQ) for manual or automated replay.

## 6. Backfill Strategy
- **Initial Seeding**: On initial POV-4 deployment, the system performs a one-time backfill using `ACCOUNT_USAGE.QUERY_HISTORY` for the past 7 days to seed the Performance Findings Store.
- **Silent Mode**: Backfill execution suppresses the Notification/Alerting module to avoid spamming communication channels, purely building the historical dataset for future RAG capabilities.
