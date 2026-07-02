# LLM Configuration & Deployment Guide

This document guides deployment engineers and system administrators on configuring the **POV-4 Query Performance Monitoring Agent** to switch between LLM providers (Google Gemini and Nvidia AI Endpoints).

---

## 1. LLM Provider Configuration Fields

You can control which LLM provider the Analysis Engine uses purely by altering environment variables (either in your terminal, Docker environment, or the `.env` file). No application code changes are required.

### Generic Configuration Variables

| Environment Variable | Description | Allowed Values / Examples |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | Selects the active LLM provider. | `gemini` (default), `nvidia` |
| `LLM_MODEL` | The model identifier to use. | `gemini-3.5-flash`, `meta/llama-3.1-8b-instruct` |
| `LLM_API_KEY` | API authentication key for the active provider. | *Secret string* |
| `LLM_BASE_URL` | Optional custom base URL (useful for NVIDIA AI Endpoints or proxy). | `https://integrate.api.nvidia.com/v1` |

### Legacy Gemini Variables (Backward Compatibility)

To prevent breaking existing configurations, the engine implements a fallback resolver. If `LLM_PROVIDER=gemini` is selected, and generic variables are not specified, it will look up:
* `GEMINI_API_KEY` (Falls back to this if `LLM_API_KEY` is empty)
* `GEMINI_MODEL_NAME` (Falls back to this if `LLM_MODEL` is empty)

---

## 2. Configuration Examples

### Example A: Running on Google Gemini (Default)
To configure the agent to use Google Gemini, add the following to your `.env` file:
```env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash
LLM_API_KEY=your_gemini_api_key_here
```
*(Alternatively, you can just use the legacy `GEMINI_API_KEY=your_gemini_api_key_here` and omit the `LLM_` parameters).*

### Example B: Running on NVIDIA AI Endpoints
To configure the agent to use the Nvidia provider (e.g. Llama 3.1 8B):
```env
LLM_PROVIDER=nvidia
LLM_MODEL=meta/llama-3.1-8b-instruct
LLM_API_KEY=your_nvidia_api_key_here
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
```

---

## 3. Local Verification & Deployment Testing

Before running a full monitoring pipeline, you should verify the connection and structured output compliance of your configured provider. 

### Quick Verification Mode
Execute the quick verification script which runs 4 targeted sub-optimal queries (Cartesian Join, Partition scan, and Disk spilling) and runs them through the ingestion, detection, and LLM analysis loop:

```bash
# Run with configured environment variables
python scratch/generate_tpch_findings.py --quick
```

Review the outputs generated inside:
`docs/ai-agent/tpch_run_results.json`

Verify that:
1. "rca" is successfully populated with explanations referencing table operator IDs.
2. "recommendations" lists specific, prioritized optimization items (e.g. `QUERY`, `WAREHOUSE`, `PARTITION_PRUNING`).
3. "llm_metadata" lists `provider` and `model` correctly matching your configuration.
