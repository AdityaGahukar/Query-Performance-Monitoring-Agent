# ADR: Architectural Correction for Confidence Scoring

## Status
Accepted

## Context
In previous iterations of the architecture, a "detection confidence score" was calculated within the Issue Detection Layer to represent telemetry completeness. However, the Issue Detection Layer is mathematically rule-based, factual, and deterministic (e.g., checking if `bytes_spilled_to_remote_storage > 0`). In deterministic rule evaluation, uncertainty does not exist. 

Confidence scoring belongs where uncertainty and probabilistic estimation exist, which is in the LLM-based Root Cause Analysis (RCA), recommendation generation, and LLM reasoning.

## Decision
1. **Remove Detection Confidence**: We have completely removed confidence scoring (`confidence_score`, `confidence_reason`, and confidence deduction rules) from the deterministic Detection Layer and the core `PerformanceFinding` model.
2. **Introduce Evidence Quality**: To track telemetry completeness without treating it as confidence, we introduced `EvidenceQuality` on the `PerformanceFinding` model. It takes three values:
   - `COMPLETE`: All telemetry sources are present.
   - `PARTIAL`: Core statistics are present, but auxiliary data (e.g., lag in attribution history or profile retrieval failure) is missing.
   - `LIMITED`: Significant telemetry is missing, indicating a sparse snapshot.
3. **Restrict Confidence to LLM Analysis**: Confidence scoring resides exclusively inside the `AnalysisResult` model as `confidence` (a `ConfidenceScore` entity with `score` and `reason`). This represents the AI agent's uncertainty in its generated RCA narrative and recommendations.

## Rationale
- **Factual Integrity**: Deterministic rule breaches are either true or false. Assigning a "confidence score" to a factual telemetry threshold breach is conceptually incorrect.
- **Precision of Uncertainty**: The AI's root cause analysis and recommendations are generative and probabilistic. Placing confidence scoring here accurately informs downstream services or users of the uncertainty of the AI reasoning.
- **Separation of Concerns**: Decoupling the completeness of telemetry data (`EvidenceQuality`) from the reasoning confidence (`ConfidenceScore`) provides clear, distinct signals to consumers (like POV-3).

## Consequences
- The domain models and DB schema contracts now separate telemetry availability (`EvidenceQuality`) from LLM reasoning accuracy (`confidence`).
- Outbound API contracts to POV-3 do not contain detection confidence scores, matching the deterministic nature of finding triggers.
