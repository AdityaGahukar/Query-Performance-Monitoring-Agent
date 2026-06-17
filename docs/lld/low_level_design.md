# Low-Level Design (LLD)

## 1. Module Interactions

The POV-4 application is built as a FastAPI service with background task processing for asynchronous pipeline execution.

### Execution Pipeline

The processing flow is managed by a central orchestrator or pipeline manager:
1. `collector.py` -> `fetch_metrics()` -> yields `TelemetrySnapshot`
2. `detector.py` -> `evaluate_rules(snapshot)` -> yields `List[DetectedIssue]`
3. `analyzer.py` -> `analyze(snapshot, issues)` -> yields `AnalysisResult`
4. `aggregator.py` -> `build_finding(snapshot, issues, analysis)` -> yields `PerformanceFinding`
5. `repository.py` -> `save(finding)`
6. `notifier.py` -> `dispatch(finding)`

## 2. API Contracts

### Integration with POV-3

**Endpoint (Downstream POV-3)**: `POST /performance-alert`
**Payload**: `PerformanceFinding` JSON representation.
**Retry Policy**: Up to 5 retries with exponential backoff.
**Idempotency**: Downstream is expected to handle idempotent processing based on `finding_id`.

### Internal API (Optional triggers / Webhooks)

**Endpoint**: `POST /api/v1/analyze-query`
**Payload**: `{"query_id": "string", "warehouse": "string"}`
**Response**: `202 Accepted` (triggers background processing pipeline for a specific historical query)

## 3. Data Models (Pydantic / ORM)

We use Pydantic models for data validation, serialization, and explicit schema definition across component boundaries.

```python
from pydantic import BaseModel, UUID4
from typing import List, Optional
from datetime import datetime

class TelemetrySnapshot(BaseModel):
    snapshot_id: UUID4
    query_id: str
    warehouse: str
    execution_time_ms: int
    queued_overload_time_ms: int
    bytes_spilled_to_local_storage: int
    bytes_spilled_to_remote_storage: int

class DetectedIssue(BaseModel):
    issue_id: UUID4
    type: str
    severity: str
    threshold_breached: str
    actual_value: float

class Recommendation(BaseModel):
    recommendation_id: UUID4
    action_type: str
    description: str
    expected_impact: str

class AnalysisResult(BaseModel):
    analysis_id: UUID4
    root_cause_summary: str
    recommendations: List[Recommendation]
    confidence_score: float
    confidence_reason: str

class PerformanceFinding(BaseModel):
    finding_id: UUID4
    timestamp: datetime
    query_id: str
    warehouse: str
    overall_severity: str
    issues: List[DetectedIssue]
    metrics: TelemetrySnapshot
    analysis: AnalysisResult
```

## 4. Detailed Component Design

### 4.1. `detector.py` (Issue Detection Engine)
Maintains a registry of `Rule` objects. Each rule implements a `check(snapshot: TelemetrySnapshot) -> Optional[DetectedIssue]` method.
Rules include:
- `RemoteSpillRule`: Checks if `bytes_spilled_to_remote_storage > threshold`.
- `WarehouseQueuingRule`: Checks if `queued_overload_time_ms > threshold`.

### 4.2. `analyzer.py` (Performance Analysis Agent)
Wraps LangChain and Gemini API. Uses a few-shot prompt template:
- **System Prompt**: Defines role as Snowflake Performance Expert.
- **Input**: Injects JSON serialized `TelemetrySnapshot` and `DetectedIssue`s.
- **Output Parser**: Uses LangChain's `PydanticOutputParser` to enforce the return of an `AnalysisResult` schema.

## 5. Failure Handling Strategy in Code

### 5.1. LLM Resilience
- **Rate Limits & Transient Errors**: Use `tenacity` library or LangChain's built-in retry mechanisms with exponential backoff.
- **Hallucinations / Formatting**: Enforce structured outputs via Pydantic. If parsing fails after retries, catch the exception and trigger a fallback mechanism.
- **Fallback**: Create a baseline `AnalysisResult` with `confidence_score = 0.0` and a default recommendation to "Manually review query profile".

### 5.2. Database Resilience
- Use SQLAlchemy with robust connection pooling. Catch `OperationalError` and retry.

### 5.3. Downstream API (POV-3) Resilience
- Implement a task queue (e.g., Celery or simpler DB-backed queue) for outbound requests.
- Failed deliveries will be recorded with `status=FAILED` in the `AlertEvent` table and retried by a sweeper cron job.
