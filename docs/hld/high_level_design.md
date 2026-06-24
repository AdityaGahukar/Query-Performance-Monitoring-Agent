# High-Level Design (HLD)

## 1. Introduction
POV-4 is an AI-assisted Query Performance Monitoring & Alerting Agent for Snowflake environments. Its primary goal is to proactively detect performance bottlenecks, perform AI-driven root cause analysis, and emit structured `PerformanceFinding` payloads for downstream consumption by POV-3 and human operators.

## 2. System Architecture Overview
The system follows an event-driven, pipeline-based architecture, composed of the following high-level phases:
1. **Data Collection Layer**: Fetch metadata from Snowflake.
2. **Issue Detection Engine**: Evaluate metrics against deterministic rules.
3. **Performance Findings Store**: Store the raw finding as the source of truth (Enabling the Detection-Only MVP).
4. **Performance Analysis Agent**: Perform Root Cause Analysis (RCA) and generate recommendations via LLM.
5. **POV-3 Integration Layer**: Notify users and trigger POV-3.

## 3. Telemetry Flow
How telemetry flows through the system to produce a `PerformanceFinding`:

1. **Ingestion**: APScheduler triggers the Data Collection Layer, pulling from `QUERY_HISTORY`, `WAREHOUSE_LOAD_HISTORY`, etc.
2. **Snapshot Creation**: The layer constructs a `TelemetrySnapshot`.
3. **Rule Evaluation**: The Monitoring Engine feeds the `TelemetrySnapshot` into the Issue Detection Engine. If thresholds are breached, it generates `DetectedIssue` records.
4. **Persistence (Raw)**: The system aggregates the snapshot and issues into a `PerformanceFinding` and saves it to the Performance Findings Store. This enables a fully functional **Detection-Only MVP**.
5. **LLM Invocation**: The `TelemetrySnapshot` and `DetectedIssue`s are packaged into a prompt for the Performance Analysis Agent.
6. **RCA & Recommendation**: The LLM returns an `AnalysisResult` containing the root cause and recommendations.
7. **Persistence (Update)**: The system updates the existing `PerformanceFinding` in the store with the analysis data.
8. **Routing**: The Notification Service constructs an `AlertEvent` to notify via Teams/Email and pushes the finding to the POV-3 endpoint.

## 4. Components & Responsibilities

### 4.1 Data Collection Layer
- **Responsibilities**: Interface with Snowflake. Execute queries against account usage views. Lazy fetch `operator_stats` (via `GET_QUERY_OPERATOR_STATS`) only when needed.
- **Inputs**: Polling triggers, configuration (Snowflake credentials).
- **Outputs**: `TelemetrySnapshot`
- **Dependencies**: Snowflake Python Connector.
- **Failure Handling**: Retry with exponential backoff on Snowflake API limits. Watermarks ensure exactly-once processing.

### 4.2 Issue Detection Engine
- **Responsibilities**: Deterministic evaluation of metrics to identify bottlenecks. Strict enforcement of rules without LLM intervention.
- **Inputs**: `TelemetrySnapshot`
- **Outputs**: List of `DetectedIssue`
- **Dependencies**: In-memory rule configurations (Thresholds).
- **Failure Handling**: Fail-open (skip to next snapshot) if rules are malformed. Log configuration errors.

### 4.3 Findings Store
- **Responsibilities**: Persist findings as the system source of truth.
- **Inputs**: `PerformanceFinding`
- **Outputs**: Stored records (Database rows).
- **Dependencies**: Snowflake internal tables (zero extra DB infrastructure).
- **Failure Handling**: Retry on Snowflake transient connection errors.

### 4.4 Performance Analysis Agent
- **Responsibilities**: Synthesize telemetry and detected issues to formulate an RCA and actionable recommendations using AI.
- **Inputs**: `TelemetrySnapshot`, List of `DetectedIssue`
- **Outputs**: `AnalysisResult`
- **Dependencies**: LangChain, Google Gemini API.
- **Failure Handling**: If the LLM times out or fails structure parsing, system proceeds with a fallback `AnalysisResult` and sets a low/zero confidence score in it.

### 4.5 POV-3 Integration & Notification Layer
- **Responsibilities**: Route alerts to Teams/Email, push findings to POV-3.
- **Inputs**: `PerformanceFinding`, `AlertEvent`
- **Outputs**: HTTP POST to POV-3, Teams/Email APIs.
- **Dependencies**: Microsoft Teams Webhook, SMTP/Email Service, POV-3 API.
- **Failure Handling**: Dead-letter queue (DLQ) for failed POV-3 API requests to ensure reliable delivery via retries driven by APScheduler.
