# Phase 5: Pre-Implementation Review & Schema Gap Analysis

This document reviews the approved Phase 5 design against the existing database tables, Pydantic domain models, and API contracts. It identifies required updates and specifies a prompt versioning strategy to ensure alignment before the implementation phase begins.

---

## 1. Schema Gap Analysis & Alignment

We evaluated the current schemas in the codebase against the Phase 5 requirements:

### Recommendation Schema Comparison
| Required LLM Output Field | Existing Pydantic `Recommendation` Field | Status / Action Needed |
| :--- | :--- | :--- |
| **`recommendation_type`** (Category) | `recommendation_type` | Align prompt to map `category` strictly to `recommendation_type`. |
| **`description`** (Recommendation) | `description` | Align prompt to map standard text description here. |
| **`expected_impact`** | `expected_impact` | Matches. |
| **`priority`** | *Missing* | **Add** `priority` (e.g., `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) to the Pydantic `Recommendation` model. |
| **`rationale`** | *Missing* | **Add** `rationale` (string explaining *why* this recommendation was made) to the `Recommendation` model. |
| **`evidence`** | *Missing* | **Add** `evidence` (string linking recommendation to telemetry like operator IDs or metrics) to the `Recommendation` model. |

### Domain Models & Storage Redesign Assessment
* **No Table Schema (DDL) Changes Required**: The findings table `POV4_PERFORMANCE_FINDINGS` stores the `ANALYSIS` block as a `VARIANT` (JSON object). Because it is schemaless in the database, expanding the Pydantic `Recommendation` and `AnalysisResult` models with new fields requires **no Snowflake DDL migrations**.
* **Pydantic Model Updates**: The class `Recommendation` in `src/domain/models.py` must be updated to support the three new fields: `priority`, `rationale`, and `evidence`.

---

## 2. Specific Verifications

### 1. Confidence Isolation
* **Verified**: Confidence scoring exists **only** inside the `AnalysisResult` Pydantic model as the `confidence` field (`ConfidenceScore` model). The deterministic layers (Telemetry snapshot, DetectedIssue, and overall PerformanceFinding) contain no LLM confidence scores, using `EvidenceQuality` instead.

### 2. Elimination of deprecated query profile calls
* **Verified**: All files in the repository have been searched. No code references or comments remain for `SYSTEM$GET_QUERY_PROFILE` or `query_profile`. All execution profile logic has been renamed to `operator_stats` / `GET_QUERY_OPERATOR_STATS`.

### 3. Operator Execution Evidence Source
* **Verified**: `GET_QUERY_OPERATOR_STATS` is the single source of operator-level plan telemetry. The collection and detection engines strictly extract and evaluate records from this function.

### 4. Telemetry Coverage
* The Analysis Engine uses the full set of telemetry data collected in the snapshot:
  * `query_history` (from `QUERY_HISTORY`)
  * `warehouse_load` (from `WAREHOUSE_LOAD_HISTORY`)
  * `metering_context` (from `METERING_HISTORY`)
  * `query_attribution` (from `QUERY_ATTRIBUTION_HISTORY`)
  * `operator_stats` (from `GET_QUERY_OPERATOR_STATS`, lazy-loaded when issues require deep execution plan analysis).

---

## 3. Prompt Versioning Strategy

To prevent prompt drift and enable seamless updates to the Analysis Engine reasoning without requiring Python code rewrites, we will use a file-based **Prompt Versioning Strategy**:

### Directory Structure
```
src/
└── agents/
    └── prompts/
        ├── __init__.py
        ├── v1_default_system.txt
        └── v1_default_user.txt
```

### Loading Mechanism
1. The prompts are stored as plain text files in the package.
2. The `QueryPerformanceAnalyzer` loads templates dynamically on startup by looking up the version specified in the settings (e.g. `SETTINGS.LLM.PROMPT_VERSION = "v1_default"`).
3. If a prompt needs to be updated (e.g., adjusting few-shot examples or changing guardrails), a new file is created (e.g., `v2_rag_system.txt`) and configured in the environment variables, requiring no python code changes.

---

## 4. Required Implementation Changes

Before code generation begins, we must apply the following structural updates:

### Step 1: Update `Recommendation` in `src/domain/models.py`
Add `priority`, `rationale`, and `evidence` fields to the model.

```python
class Recommendation(BaseModel):
    recommendation_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this recommendation.",
    )
    recommendation_type: str = Field(
        description="Category label for this recommendation, e.g. 'QUERY', 'WAREHOUSE'.",
        min_length=1,
    )
    description: str = Field(
        description="Full human-readable description of the recommended action.",
        min_length=1,
    )
    expected_impact: str = Field(
        description="LLM-generated statement of the expected impact.",
        min_length=1,
    )
    priority: str = Field(
        description="Priority of the action: e.g., 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'.",
        min_length=1,
    )
    rationale: str = Field(
        description="Explanation of why this action is recommended.",
        min_length=1,
    )
    evidence: str = Field(
        description="Telemetry evidence justifying the action (e.g., 'Aggregate operator spilled 4.5GB').",
        min_length=1,
    )
```

### Step 2: Update Prompts and Contracts Documents
Align `docs/ai-agent/phase5-AI-Agentcontracts.md` and `docs/ai-agent/prompting-strategy.md` to output the new fields in the JSON formats and examples.
