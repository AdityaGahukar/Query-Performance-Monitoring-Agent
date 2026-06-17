# Proposed Project Structure & Module Responsibilities

## Directory Layout

```text
pov4/
├── src/
│   ├── api/
│   │   ├── routes.py          # FastAPI endpoints (e.g., manual trigger)
│   │   ├── dependencies.py    # DI containers, DB sessions
│   ├── core/
│   │   ├── config.py          # Environment variables and settings
│   │   ├── exceptions.py      # Custom domain exceptions
│   │   ├── logger.py          # Structured logging
│   ├── domain/
│   │   ├── models.py          # Core Entities (TelemetrySnapshot, PerformanceFinding)
│   ├── services/
│   │   ├── collector.py       # Snowflake data ingestion
│   │   ├── detector.py        # Rule-based evaluation engine
│   │   ├── aggregator.py      # Finding assembly logic
│   ├── agents/
│   │   ├── analyzer.py        # LangChain + Gemini integration for RCA
│   │   ├── prompts.py         # Prompt templates
│   ├── integrations/
│   │   ├── teams.py           # MS Teams webhook client
│   │   ├── pov3_client.py     # API client for POV-3 POST requests
│   ├── storage/
│   │   ├── repository.py      # Persistence logic for findings
├── docs/
│   ├── hld/
│   ├── lld/
│   ├── architecture/
│   ├── domain-model/
│   ├── adr/
├── tests/
│   ├── unit/
│   ├── integration/
├── Dockerfile
├── requirements.txt
├── .env.example
```

## Module Responsibilities

- **`src/api/`**: Exposes HTTP interfaces. Handles incoming requests for health checks, manual ingestion triggers, or querying past findings. Acts as the presentation layer.
- **`src/core/`**: Cross-cutting concerns. Manages application state, configurations, and standardized logging for observability.
- **`src/domain/models.py`**: Contains the absolute source of truth for the schemas of `PerformanceFinding` and its sub-components. Independent of any specific database or framework, relying primarily on Pydantic.
- **`src/services/collector.py`**: Interfaces strictly with Snowflake to retrieve telemetry. Decoupled from analysis logic.
- **`src/services/detector.py`**: Holds the deterministic rules. It strictly isolates the business logic of "What constitutes a spill?" from the AI layer.
- **`src/services/aggregator.py`**: Coordinates the pipeline, joining the outputs of the collector, detector, and analyzer into the final `PerformanceFinding` artifact.
- **`src/agents/analyzer.py`**: The AI core. Manages the LLM context window, builds prompts, and parses LLM outputs back into `AnalysisResult` Pydantic models.
- **`src/integrations/pov3_client.py`**: Ensures the contract with POV-3 is met, handling serialization, network calls, and HTTP retry logic.
- **`src/storage/repository.py`**: Abstracts the database interactions, providing a clean interface to save and load `PerformanceFinding`s.
