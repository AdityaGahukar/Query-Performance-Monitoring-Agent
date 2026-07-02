# Phase 5 Design Decisions

This document details the architectural decisions made for the implementation of the **Phase 5 Analysis Engine (LLM Layer)**.

---

## Decision 1: Primary LLM Choice & Provider Abstraction

### Status
Accepted / Enhanced

### Context
We need to select LLM providers that offer reliable performance, structured output parsing, low latency, and cost efficiency. We also need to design the architecture to accommodate multiple providers (e.g. Gemini, Nvidia, etc.) and allow switching between them purely via configuration.

### Decision
1. **Google Gemini (specifically `gemini-3.5-flash`)** is the primary default model.
2. **Nvidia AI Endpoints** is supported as an alternative provider using `langchain_nvidia_ai_endpoints.ChatNVIDIA`.
3. We implement an `LLMProvider` abstract base class to decouple provider-specific client libraries from the core analysis service logic. Selecting between providers is done via the `LLM_PROVIDER` environment variable.

### Rationale
- **Economics**: Both models are highly cost-effective for high-frequency telemetry logging pipelines.
- **Structured Support**: Gemini uses native structured output, while the Nvidia provider utilizes native structured output with a robust JSON-only validation + retry fallback to guarantee Pydantic validation success.
- **Flexibility**: Abstracting provider invocation allows developers to switch models seamlessly through environment variables without any code modifications.

---

## Decision 2: Single-Prompt Execution vs. Multi-Agent/LangGraph Loops

### Status
Accepted (Reference: [ADR-0002](file:///Users/as-mac-1299/Intern%20Projects/Snowflake%20Performance%20Monitoring/docs/adr/0002-single-agent-architecture.md))

### Context
A performance finding can be analyzed using a multi-agent loop (e.g. one agent for RCA, one for recommendations, one for verification) or a single prompt invocation that returns a combined, fully-formed output structure.

### Decision
We will use a single prompt execution cycle via a single LLM invocation. We will not use multi-agent setups, LangGraph loops, conversational memory, or self-correction loops.

### Rationale
- **Latency**: Multi-agent conversational turns multiply API latency (e.g., 3 agents can take 8-15 seconds). A single Gemini call typically resolves in under 1.5 seconds.
- **Simplicity**: Single-agent setups are significantly easier to debug, test, maintain, and unit test.
- **Cohesion**: Generating RCA and recommendations in the same context window yields highly aligned suggestions, as the model's reasoning about the cause directly informs its optimization solutions.

---

## Decision 3: Zero-Tool Call (RAG) Architecture

### Status
Accepted

### Context
Should the LLM agent have active Snowflake credentials to run commands like `EXPLAIN` or query historical tables on-demand to fetch more details, or should all telemetry be pre-collected and compiled by the Python application?

### Decision
We will employ a **Zero-Tool Call** architecture. The Analysis Engine is completely sandboxed: it does not have database connections, API keys to Snowflake, or local file execution capabilities. The Python aggregator compiles all necessary telemetry (metrics, history, pruned operator stats) and passes it in the context of the prompt.

### Rationale
- **Security**: Granting an LLM direct SQL write or read access to enterprise database accounts creates significant prompt-injection vulnerabilities (e.g., executing arbitrary queries or dropping tables).
- **Latency & Reliability**: On-demand query execution by the LLM would introduce unpredictable API round-trips and timeouts.
- **Separation of Concerns**: The Python telemetry collector is responsible for data gathering, and the detector is responsible for issue identification. The LLM is purely an inference engine.

---

## Decision 4: Deterministic Source of Truth Guardrail

### Status
Accepted

### Context
If the LLM believes that a `REMOTE_SPILL` issue was actually caused by a poor partition scan, should it be allowed to rename the issue type or override the severity from `MEDIUM` to `HIGH`?

### Decision
No. The deterministic Detection Engine is the absolute source of truth. The LLM cannot:
- Re-detect issues
- Override severity levels
- Override threshold definitions
- Challenge deterministic findings

If the LLM has contradictory theories, it can express its reasoning in the `root_cause_summary` or lower its confidence score, but it must never modify the core finding metadata.

### Rationale
- **Consistency**: Deterministic rules ensure that findings align strictly with company SLAs and mathematical thresholds. 
- **Operational Safety**: If an operator sets a rule for CPU utilization > 90% as `CRITICAL`, the LLM must not downgrade it to `LOW` due to speculative reasoning, which would bypass alerts and monitoring channels.

---

## Decision 5: On-Demand Operator Stats Pruning

### Status
Accepted

### Context
Individual query plans can have thousands of operators. Passing all operator metadata to the prompt increases cost and adds noise.

### Decision
The Python aggregator prunes the `operator_stats` array before prompt compilation. It filters to include only:
- Nodes that spilled to remote or local storage.
- Nodes with high execution time fractions (top N).
- Exploding join operators or Table Scans scanning > 50% partitions.
The prompt context is limited to a maximum of 10 operators.

### Rationale
- **Signal-to-Noise**: Filters out hundreds of trivial operations (e.g. projection, metadata filtering) to focus LLM reasoning on the actual bottleneck operators.
- **Token Efficiency**: Keeps input sizes small, lowering API billing costs and staying well within latency limits.

---

## Decision 6: Error Handling & Graceful Fallback

### Status
Accepted

### Context
If Gemini times out, experiences rate limits, or outputs corrupt JSON, how should the pipeline respond?

### Decision
1. **Retry Policy**: Configure 2 retries with exponential backoff for transient provider failures.
2. **JSON Repair**: Use Pydantic parsing and retry prompt loops if output is syntactically invalid.
3. **Null Fallback**: If all retries fail, the analyzer logs the incident to the DLQ table and returns `None` for the `analysis` block of the finding. The finding is saved with detection details intact, preventing pipeline halts.

### Rationale
- **Resilience**: Telemetry logging must never be blocked by downstream third-party AI service outages. Persisting a finding without LLM explanations is always preferred over dropping the telemetry batch entirely.
- **Observability**: DLQ routing ensures that failed LLM calls are visible to administrators for debugging or re-evaluation.
