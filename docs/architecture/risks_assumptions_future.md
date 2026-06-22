# Risks, Assumptions, and Future Extensibility Considerations

## Assumptions
1. **Upstream Data Freshness**: We assume Snowflake's `QUERY_HISTORY` and `WAREHOUSE_LOAD_HISTORY` are sufficiently real-time for our alerting needs (understanding that some `ACCOUNT_USAGE` views may have latency compared to `INFORMATION_SCHEMA`).
2. **POV-3 Availability**: We assume POV-3 exposes a highly available `POST /performance-alert` webhook that is capable of receiving asynchronous payloads.
3. **LLM Structured Output**: We assume the Google Gemini API can reliably adhere to a strict JSON schema for the `AnalysisResult` entity, allowing seamless parsing back into Python objects.

## Risks & Mitigation Strategy
1. **Snowflake API Rate Limiting**: Continually polling Snowflake for telemetry might hit API limits or consume unnecessary compute credits.
   - *Mitigation*: Use batch processing and stateful cursors (watermarks) to only fetch delta telemetry. Target `ACCOUNT_USAGE` where latency is acceptable to reduce warehouse costs.
2. **LLM Hallucination on RCA**: The LLM might suggest irrelevant Snowflake features or hallucinate root causes.
   - *Mitigation*: Provide strict system instructions, inject only highly relevant metric attributes (avoiding overwhelming raw logs), and require the LLM to output a `confidence` score within the `AnalysisResult` that downstream consumers can filter by.
3. **Data Volume Overload (Alert Fatigue)**: A suddenly poorly written query in a loop could generate thousands of identical issues per minute.
   - *Mitigation*: Implement deduplication and rate-limiting at the aggregation layer before sending `AlertEvent`s. Group similar `PerformanceFinding`s by `query_id` hash or `warehouse`.

## Future Extensibility Considerations
- **RAG (Retrieval-Augmented Generation) Implementation**: The system stores all historical `PerformanceFinding`s. In the future, a Vector Database can be integrated so the LLM can query past similar incidents to improve its RCA and provide historical context.
- **Dynamic Thresholding**: Move from static rule-based thresholds in the Issue Detection Engine to Machine Learning-based anomaly detection (e.g., using moving averages or seasonal trend decomposition) for `DetectedIssue` generation.
- **Multi-tenant Support**: The Domain Model includes `warehouse`, but could easily be extended to support multiple Snowflake Organizations or Accounts via an `account_id` attribute, scaling the observability platform.
