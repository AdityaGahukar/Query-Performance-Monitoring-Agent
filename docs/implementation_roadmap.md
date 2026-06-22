# POV-4 Implementation Roadmap

This document outlines the phased approach to building POV-4 from an empty repository to a fully functional V1 system.

---

## Phase 1: Foundation & Domain Layer

**Goal:** 
Establish the project skeleton, configure cross-cutting concerns (logging, config), and implement the absolute source of truth for the system: the Domain Models.

**Deliverables:**
- Initialized Python repository with FastAPI skeleton.
- Configured environment variable management (`core/config.py`).
- Pydantic models in `domain/models.py` (`TelemetrySnapshot`, `DetectedIssue`, `PerformanceFinding`, etc.).

**Dependencies:** 
- None.

**Test Strategy:** 
- Pure unit tests validating Pydantic model serialization, deserialization, and strict typing.

**Success Criteria:** 
- All domain entities can be instantiated and validated.
- `make test` passes with 100% coverage on the domain layer.

---

## Phase 2: Telemetry Data Collection Layer

**Goal:** 
Implement the Snowflake integration capable of querying the V1 telemetry sources and managing stateful watermarks.

**Deliverables:**
- `services/collector.py` using `snowflake-connector-python`.
- Watermark tracking logic.
- Dedicated functions for `QUERY_HISTORY`, `WAREHOUSE_LOAD_HISTORY`, `METERING_HISTORY`, and `QUERY_ATTRIBUTION_HISTORY`.
- Lazy, on-demand `query_profile` fetcher (using `GET_QUERY_OPERATOR_STATS`).

**Architectural Constraint:**
- `query_profile` retrieval must be **lazy and on-demand**. Never fetch profiles for all queries. Only fetch profiles for candidate queries explicitly identified by the Detection Engine.

**Dependencies:** 
- Phase 1 (Domain Models).
- Snowflake service account credentials with `MONITOR` privileges.

**Test Strategy:** 
- **Unit Tests:** Mock the Snowflake cursor to return static JSON.
- **Integration Tests:** Connect to a Snowflake sandbox and fetch recent telemetry.

**Success Criteria:** 
- The collector successfully authenticates, queries `INFORMATION_SCHEMA`, updates the watermark, and populates a valid `TelemetrySnapshot` object.

---

## Phase 3: Deterministic Issue Detection Engine

**Goal:** 
Build the rule-based engine that mathematically evaluates telemetry against configured thresholds to detect bottlenecks.

**Deliverables:**
- `services/detector.py` with the Rule Registry.
- Implementations for the core issues (e.g., `REMOTE_SPILL`, `COST_ANOMALY`).
- Severity calculation logic.
- Telemetry completeness / EvidenceQuality logic.

**Dependencies:** 
- Phase 1 (Domain Models).

**Test Strategy:** 
- Data-driven unit testing. Feed the engine mock `TelemetrySnapshot`s with values just below and just above thresholds to ensure boundary conditions are met.

**Success Criteria:** 
- The engine accurately flags an issue, assigns the correct severity, determines the EvidenceQuality, and returns a valid list of `DetectedIssue`s. 
- The detection engine processes snapshots efficiently and deterministically.

---

## Phase 4: Persistence Layer

**Goal:** 
Establish the database layer to store `TelemetrySnapshot`, `DetectedIssue`, and `PerformanceFinding` entities.

**Deliverables:**
- `storage/repository.py` to persist findings.
- Database schema scripts (DDL).

**Architectural Decision:**
- **Store findings in Snowflake internal tables**. Since POV-4 is already connected to Snowflake for telemetry, this requires no extra infrastructure, and provides easy analytics, dashboarding, and historical RCA.

**Dependencies:** 
- Phases 1-3.
- Snowflake target database/schema for POV-4 storage.

**Test Strategy:** 
- Integration tests using a test Snowflake schema to verify insertion and retrieval of raw snapshot and finding JSON.

**Success Criteria:** 
- Entities can be seamlessly written to and retrieved from Snowflake internal tables.

---

### 🚀 Milestone 1: Detection-Only MVP
At the conclusion of Phase 4, POV-4 is a usable product. The system can ingest Snowflake telemetry, pass it through the deterministic detection engine, and persist raw findings (e.g., a "REMOTE_SPILL" with "HIGH" severity) directly to Snowflake. This validates the telemetry strategy, detection rules, and severity models using real historical data before introducing any LLM complexity.

---

## Phase 5: RCA Agent (Gemini)

**Goal:** 
Integrate LangChain and Google Gemini to synthesize detected issues into Root Cause Analysis (RCA) and actionable recommendations.

**Deliverables:**
- `agents/analyzer.py` handling LLM invocation.
- System prompt and few-shot templates (`agents/prompts.py`).
- Pydantic Output Parser to enforce structured JSON responses.

**Dependencies:** 
- Phases 1-4.
- Google Gemini API key.

**Test Strategy:** 
- **Unit Tests:** Mock the LLM HTTP response to test the Pydantic Output Parser's resilience to malformed JSON.
- **E2E Tests:** Execute real API calls against Gemini using historically captured `query_profile` JSON strings.

**Success Criteria:** 
- The LLM consistently processes a `TelemetrySnapshot` + `DetectedIssue`s and returns a valid `AnalysisResult` containing root causes and recommendations.

---

## Phase 6: Orchestration

**Goal:** 
Tie the collector, detector, and analyzer together into a continuous background processing pipeline.

**Deliverables:**
- `services/aggregator.py` to assemble the complete `PerformanceFinding`.
- Pipeline task scheduler using **APScheduler** (avoiding Celery/Redis to keep the architecture simple).

**Dependencies:** 
- Phases 1-5.

**Test Strategy:** 
- Integration tests spanning the entire pipeline using mock Snowflake data.

**Success Criteria:** 
- APScheduler continuously runs jobs end-to-end: fetches telemetry, detects an issue, gets an analysis, and saves a complete `PerformanceFinding` row to the database.

---

## Phase 7: Notifications + POV3

**Goal:** 
Ensure findings are communicated to human operators and dispatched to downstream automation systems reliably.

**Deliverables:**
- `integrations/teams.py` for Microsoft Teams webhooks.
- `integrations/pov3_client.py` for `POST /performance-alert`.
- HTTP retry mechanisms and Dead Letter Queue (DLQ) for outbound failures.

**Dependencies:** 
- Phase 6.
- POV-3 webhook URL and API contract.

**Test Strategy:** 
- Use HTTP mocking libraries to simulate POV-3 downtime to verify exponential backoff and DLQ routing.

**Success Criteria:** 
- `AlertEvent` is successfully transmitted to Teams and POV-3. Failed requests are safely caught and queued for retry.

---

## Phase 8: Deployment & Backfill

**Goal:** 
Deploy the application, run the historical backfill, and validate production readiness.

**Deliverables:**
- Dockerfile & CI/CD pipeline.
- Execution of the historical backfill script.
- Live monitoring dashboards for POV-4 internals.

**Architectural Constraint for Backfill:**
- The backfill script must:
  - Generate findings.
  - Store findings.
  - **Do NOT send notifications.**
  - **Do NOT call POV-3.**
  (This prevents 200+ historical alerts from suddenly firing and spamming channels).

**Dependencies:** 
- All previous phases.
- Cloud deployment environment.

**Test Strategy:** 
- Real-world soak test against a non-production Snowflake account.

**Success Criteria:** 
- System runs continuously for 48 hours without memory leaks.
- Historical telemetry is successfully analyzed and stored, validating the RAG foundation without triggering false alarms.
