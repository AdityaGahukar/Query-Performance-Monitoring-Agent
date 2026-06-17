# High-Level Design (HLD)

## 1. Introduction
POV-4 is an AI-assisted Query Performance Monitoring & Alerting Agent for Snowflake environments. Its primary goal is to proactively detect performance bottlenecks, perform AI-driven root cause analysis, and emit structured `PerformanceFinding` payloads for downstream consumption by POV-3 and human operators.

## 2. System Architecture Overview
The system follows an event-driven, pipeline-based architecture, composed of the following high-level phases:
1. **Data Collection Layer**: Fetch metadata from Snowflake.
2. **Issue Detection Engine**: Evaluate metrics against deterministic rules.
3. **Performance Analysis Agent**: Perform Root Cause Analysis (RCA) and generate recommendations via LLM.
4. **Performance Findings Store**: Store the finding as the source of truth.
5. **POV-3 Integration Layer**: Notify users and trigger POV-3.

## 3. Telemetry Flow
How telemetry flows through the system to produce a `PerformanceFinding`:

1. **Ingestion**: A cron job or event bridge triggers the Data Collection Layer, pulling from `QUERY_HISTORY`, `WAREHOUSE_LOAD_HISTORY`, etc.
2. **Snapshot Creation**: The layer constructs a `TelemetrySnapshot`.
3. **Rule Evaluation**: The Monitoring Engine feeds the `TelemetrySnapshot` into the Issue Detection Engine. If thresholds (e.g., remote spills > X GB) are breached, it generates one or more `DetectedIssue` records.
4. **LLM Invocation**: If issues are detected, the `TelemetrySnapshot` and `DetectedIssue`s are packaged into a prompt for the Performance Analysis Agent (Google Gemini API via LangChain).
5. **RCA & Recommendation**: The LLM returns an `AnalysisResult` containing the root cause, recommendations, and a confidence score.
6. **Aggregation**: The system aggregates the `TelemetrySnapshot`, `DetectedIssue`s, and `AnalysisResult` into a single `PerformanceFinding`.
7. **Storage & Routing**: The `PerformanceFinding` is saved to the Performance Findings Store. The Notification Service constructs an `AlertEvent` to notify via Teams/Email and pushes the finding to the POV-3 endpoint.

## 4. Components & Responsibilities

### 4.1 Data Collection Layer
- **Responsibilities**: Interface with Snowflake. Execute queries against account usage views and construct metrics.
- **Inputs**: Polling triggers, configuration (Snowflake credentials).
- **Outputs**: `TelemetrySnapshot`
- **Dependencies**: Snowflake Python Connector.
- **Failure Handling**: Retry with exponential backoff on Snowflake API limits. Alert on persistent authentication failures. Fail-safe to avoid infinite loops if metadata views are delayed.

### 4.2 Issue Detection Engine
- **Responsibilities**: Deterministic evaluation of metrics to identify bottlenecks. Strict enforcement of rules without LLM intervention.
- **Inputs**: `TelemetrySnapshot`
- **Outputs**: List of `DetectedIssue`
- **Dependencies**: In-memory rule configurations (Thresholds).
- **Failure Handling**: Fail-open (skip to next snapshot) if rules are malformed. Log configuration errors.

### 4.3 Performance Analysis Agent
- **Responsibilities**: Synthesize telemetry and detected issues to formulate an RCA and actionable recommendations using AI.
- **Inputs**: `TelemetrySnapshot`, List of `DetectedIssue`
- **Outputs**: `AnalysisResult`
- **Dependencies**: LangChain, Google Gemini API.
- **Failure Handling**: If the LLM times out or fails structure parsing, generate a fallback `AnalysisResult` indicating "LLM Analysis Unavailable" with a confidence score of 0.0, to ensure the pipeline still produces a `PerformanceFinding`.

### 4.4 Findings Store
- **Responsibilities**: Persist findings as the system source of truth.
- **Inputs**: `PerformanceFinding`
- **Outputs**: Stored records (Database rows).
- **Dependencies**: Relational Database (e.g., PostgreSQL or Snowflake itself).
- **Failure Handling**: Buffer to local disk or memory queue if DB is temporarily unavailable.

### 4.5 POV-3 Integration & Notification Layer
- **Responsibilities**: Route alerts to Teams/Email, push findings to POV-3.
- **Inputs**: `PerformanceFinding`, `AlertEvent`
- **Outputs**: HTTP POST to POV-3, Teams/Email APIs.
- **Dependencies**: Microsoft Teams Webhook, SMTP/Email Service, POV-3 API.
- **Failure Handling**: Dead-letter queue (DLQ) for failed POV-3 API requests to ensure reliable delivery via retries. Fallback to Email if Teams webhook fails.
