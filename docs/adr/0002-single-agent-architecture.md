# ADR 2: Single Analysis Agent vs. Multi-Agent Architecture

## Status
Accepted

## Context
For the AI-assisted analysis phase, we could build a multi-agent system (e.g., one agent for RCA, one for Recommendations, one for LLM confidence scoring) or a single monolithic analysis agent that performs all tasks in one go.

## Decision
We will use a Single Analysis Agent implemented via LangChain to handle Root Cause Analysis (RCA), generating recommendations, and computing the LLM Analysis Layer confidence score within a single prompt/response cycle.

## Rationale
- **Simplicity**: The project principles explicitly state "Avoid unnecessary multi-agent complexity." Maintaining one robust prompt is easier than managing conversational state across multiple agents.
- **Latency**: A single LLM call significantly reduces end-to-end latency compared to a chained multi-agent dialogue.
- **Cohesion**: RCA, recommendations, and analysis confidence are highly cohesive; the LLM generates better, more context-aware recommendations when it has just derived the root cause in the exact same context window.

## Consequences
- Requires a carefully crafted, comprehensive prompt.
- We must utilize Structured Outputs (JSON schema enforcement) to ensure all three pieces of data (RCA, recommendations, LLM analysis confidence) are reliably extracted from the single response payload.
