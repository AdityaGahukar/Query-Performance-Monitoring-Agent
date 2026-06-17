# ADR 1: Deterministic Issue Detection vs. LLM-based Detection

## Status
Accepted

## Context
POV-4 needs to identify performance bottlenecks like remote spills and warehouse queuing from raw Snowflake telemetry. We have the option to feed raw telemetry directly into an LLM to identify issues (allowing the LLM to deduce if a metric represents an issue), or use a traditional rule-based engine prior to the LLM step.

## Decision
We will use a deterministic, rule-based engine (e.g., simple Python threshold checks) for Issue Detection. The LLM will ONLY be invoked subsequently for Root Cause Analysis (RCA) and generating recommendations.

## Rationale
- **Reliability & Accuracy**: Mathematical thresholds (e.g., `bytes_spilled > 1GB`) are binary and deterministic. LLMs can hallucinate, fail to do basic arithmetic consistently, or misinterpret the scale of a metric.
- **Cost & Performance**: Evaluating rules in code is computationally cheap and instantaneous. Sending millions of query metrics to an LLM continuously is cost-prohibitive and slow.
- **Explainability**: A rule breach is perfectly auditable. We can definitively say "This was flagged because Rule X breached Threshold Y".

## Consequences
- Requires maintaining configuration thresholds (e.g., defining what constitutes a "large" spill).
- Ensures the LLM is only invoked when an actual issue has been mathematically proven to exist, saving significant API costs and reducing system latency.
