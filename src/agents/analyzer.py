"""
POV-4: Performance Analysis Agent.

Processes detected query performance bottlenecks using Google Gemini (via LLMProvider)
and provides detailed root cause analysis narrative and actionable recommendations.
"""

import json
import os
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from src.core.config import Settings
from src.core.logging import get_logger
from src.domain.enums import IssueType
from src.domain.models import AnalysisResult, DetectedIssue, Recommendation, ConfidenceScore, TelemetrySnapshot
from src.agents.providers import LLMProvider, LLMProviderError, LLMTimeoutError, LLMValidationError

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Prompt Utility
# ---------------------------------------------------------------------------

def load_prompt_templates(version: str) -> tuple[str, str]:
    """
    Dynamically loads the system and user prompt templates based on version.
    """
    base_dir = os.path.dirname(__file__)
    system_path = os.path.join(base_dir, "prompts", f"{version}_system.txt")
    user_path = os.path.join(base_dir, "prompts", f"{version}_user.txt")

    if not os.path.exists(system_path):
        raise FileNotFoundError(f"System prompt template version '{version}' not found at: {system_path}")
    if not os.path.exists(user_path):
        raise FileNotFoundError(f"User prompt template version '{version}' not found at: {user_path}")

    with open(system_path, "r", encoding="utf-8") as f:
        system_template = f.read()
    with open(user_path, "r", encoding="utf-8") as f:
        user_template = f.read()

    return system_template, user_template


# ---------------------------------------------------------------------------
# Operator Stats Pruning Algorithm
# ---------------------------------------------------------------------------

def prune_operator_stats(
    operator_stats: Optional[List[Dict[str, Any]]], 
    issues: List[DetectedIssue],
    max_operators: int = 10
) -> List[Dict[str, Any]]:
    """
    Prunes the raw list of operator execution stats to contain only the most 
    performance-affecting nodes (up to max_operators).
    """
    if not operator_stats:
        return []

    pruned: Dict[int, Dict[str, Any]] = {}
    
    # Check what issues were detected
    has_poor_pruning = any(issue.type == IssueType.POOR_PARTITION_PRUNING for issue in issues)

    # Fields to extract for the prompt
    target_fields = {
        "OPERATOR_ID", "OPERATOR_TYPE", "EXECUTION_TIME_FRACTION",
        "RECORDS_PRODUCED", "RECORDS_SCANNED", "BYTES_SPILLED_LOCAL",
        "BYTES_SPILLED_REMOTE", "PARTITIONS_SCANNED", "PARTITIONS_TOTAL"
    }

    def clean_operator(op: Dict[str, Any]) -> Dict[str, Any]:
        return {k: op.get(k) for k in target_fields if k in op}

    # 1. Include Spill Nodes (memory thrashing indicator)
    for op in operator_stats:
        spilled_local = op.get("BYTES_SPILLED_LOCAL", 0) or 0
        spilled_remote = op.get("BYTES_SPILLED_REMOTE", 0) or 0
        if spilled_local > 0 or spilled_remote > 0:
            op_id = op.get("OPERATOR_ID")
            if op_id is not None:
                pruned[op_id] = clean_operator(op)

    # 2. Include Exploding Row Nodes (Cartesian join indicators)
    for op in operator_stats:
        records_produced = op.get("RECORDS_PRODUCED", 0) or 0
        records_scanned = op.get("RECORDS_SCANNED", 0) or 0
        if records_scanned > 0:
            ratio = records_produced / records_scanned
            if ratio > 2.0 and records_produced > 100_000:
                op_id = op.get("OPERATOR_ID")
                if op_id is not None:
                    pruned[op_id] = clean_operator(op)

    # 3. Include Scan & Filter Nodes for poor partition pruning
    if has_poor_pruning:
        for op in operator_stats:
            op_type = str(op.get("OPERATOR_TYPE", "")).upper()
            if "SCAN" in op_type or "FILTER" in op_type:
                partitions_scanned = op.get("PARTITIONS_SCANNED", 0) or 0
                partitions_total = op.get("PARTITIONS_TOTAL", 0) or 0
                if partitions_total > 0 and (partitions_scanned / partitions_total) > 0.5:
                    op_id = op.get("OPERATOR_ID")
                    if op_id is not None:
                        pruned[op_id] = clean_operator(op)

    # 4. Include Bottleneck Nodes (Sort remaining nodes by execution fraction and take the top ones)
    remaining_ops = [op for op in operator_stats if op.get("OPERATOR_ID") not in pruned]
    remaining_ops.sort(key=lambda op: op.get("EXECUTION_TIME_FRACTION", 0) or 0, reverse=True)

    for op in remaining_ops:
        if len(pruned) >= max_operators:
            break
        op_id = op.get("OPERATOR_ID")
        if op_id is not None:
            pruned[op_id] = clean_operator(op)

    # Final pruning check to limit strictly to max_operators
    final_list = list(pruned.values())
    if len(final_list) > max_operators:
        # If we somehow exceeded, keep the ones with highest execution time fraction
        final_list.sort(key=lambda op: op.get("EXECUTION_TIME_FRACTION", 0) or 0, reverse=True)
        final_list = final_list[:max_operators]

    return final_list


# ---------------------------------------------------------------------------
# Analyzer Class Implementation
# ---------------------------------------------------------------------------

class QueryPerformanceAnalyzer:
    """
    Orchestrates prompt loading, operator stats pruning, structured output parsing,
    and metadata tracing for query performance diagnostics.
    """

    def __init__(self, provider: LLMProvider, settings: Settings):
        self.provider = provider
        self.settings = settings

    def analyze_finding(
        self,
        snapshot: TelemetrySnapshot,
        issues: List[DetectedIssue],
        operator_stats: Optional[List[Dict[str, Any]]] = None
    ) -> AnalysisResult:
        """
        Synthesizes detected performance issues and telemetry into a validated AnalysisResult.
        """
        logger.info("Executing performance analysis for query ID", extra={
            "query_id": snapshot.query_id,
            "detected_issues_count": len(issues),
            "raw_operator_stats_count": len(operator_stats) if operator_stats else 0
        })

        if not issues:
            raise ValueError("Cannot analyze finding: list of detected issues cannot be empty.")

        # 1. Prune operator statistics using context boundaries
        pruned_ops = prune_operator_stats(operator_stats, issues, max_operators=10)
        logger.debug("Pruned operator statistics completed", extra={
            "pruned_operators_count": len(pruned_ops)
        })

        # 2. Format user data inputs
        formatted_issues = [
            {
                "type": issue.type.value,
                "severity": issue.severity.value,
                "threshold_breached": issue.threshold_breached,
                "actual_value": issue.actual_value,
            }
            for issue in issues
        ]

        formatted_user_prompt = {
            "detected_issues": json.dumps(formatted_issues, indent=2),
            "query_history": json.dumps(snapshot.query_history, indent=2),
            "operator_stats": json.dumps(pruned_ops, indent=2),
            "warehouse_load": json.dumps(snapshot.warehouse_load, indent=2),
            "query_attribution": json.dumps(snapshot.query_attribution, indent=2),
        }

        # 3. Load versioned prompt templates
        version = self.settings.gemini.prompt_version
        try:
            system_template, user_template_raw = load_prompt_templates(version)
        except FileNotFoundError as e:
            logger.error("Failed to load prompt templates", extra={"error": str(e)})
            raise LLMValidationError(f"Prompt template configuration error: {e}")

        # Interpolate variables into user template
        user_prompt = user_template_raw.format(**formatted_user_prompt)

        # 4. Invoke LLM provider with retry policy
        max_retries = self.settings.gemini.max_retries
        timeout_seconds = self.settings.gemini.request_timeout_seconds
        
        retries_count = 0
        validation_failures: List[str] = []
        raw_result = None
        start_time = time.perf_counter()

        while True:
            try:
                # We enforce structured output via Pydantic model directly or raw parse
                # LangChain will enforce parsing against this Pydantic model or throw validation error
                class AnalysisOutputSchema(BaseModel):
                    root_cause_summary: str
                    confidence: ConfidenceScore
                    recommendations: list[Recommendation]

                # Invoke the Gemini provider
                raw_result = self.provider.generate(
                    system_instruction=system_template,
                    user_prompt=user_prompt,
                    response_schema=AnalysisOutputSchema,
                    temperature=0.0,
                    timeout_seconds=timeout_seconds,
                )
                
                # Validate the response dictionary against the expected Pydantic schema
                if isinstance(raw_result, dict):
                    AnalysisOutputSchema(**raw_result)
                else:
                    raise LLMValidationError(f"Expected dict response, got: {type(raw_result)}")
                break

            except (LLMProviderError, LLMTimeoutError) as e:
                retries_count += 1
                if retries_count > max_retries:
                    logger.error("LLM Provider failed after maximum retries", extra={
                        "query_id": snapshot.query_id,
                        "retries": retries_count,
                        "error": str(e)
                    })
                    raise
                logger.warning(f"Transient LLM failure (attempt {retries_count}/{max_retries}), retrying...", extra={
                    "error": str(e)
                })
                time.sleep(1.0 * retries_count)  # Simple incremental backoff

            except Exception as e:
                # Pydantic parsing / formatting exception
                error_entry = {
                    "error": str(e),
                    "raw_response": raw_result if isinstance(raw_result, dict) else str(raw_result)
                }
                validation_failures.append(error_entry)
                retries_count += 1
                if retries_count > max_retries:
                    logger.error("LLM validation/parsing failed after maximum retries", extra={
                        "query_id": snapshot.query_id,
                        "validation_errors": validation_failures
                    })
                    raise LLMValidationError(f"Failed to generate valid schema matching AnalysisResult: {e}")
                logger.warning(f"Validation failure (attempt {retries_count}/{max_retries}), retrying...", extra={
                    "error": str(e)
                })
                time.sleep(1.0 * retries_count)

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # Construct final LLM metadata trace dictionary
        llm_metadata = {
            "provider": "gemini",
            "model": self.settings.gemini.model_name,
            "prompt_version": self.settings.gemini.prompt_version,
            "latency_ms": latency_ms,
            "success": True,
            "validation_failures": validation_failures if validation_failures else None,
        }

        # 6. Parse and instantiate the final domain AnalysisResult model
        try:
            # Reconstruct list of Recommendation objects to ensure UUID generation works as expected
            recs_data = raw_result.get("recommendations", [])
            recommendations = []
            for rec in recs_data:
                # If recommendations already have UUID fields, use them, otherwise they auto-generate
                recommendations.append(
                    Recommendation(
                        recommendation_type=rec.get("recommendation_type"),
                        description=rec.get("description"),
                        expected_impact=rec.get("expected_impact"),
                        priority=rec.get("priority"),
                        rationale=rec.get("rationale"),
                        evidence=rec.get("evidence"),
                    )
                )

            analysis_res = AnalysisResult(
                root_cause_summary=raw_result.get("root_cause_summary"),
                recommendations=recommendations,
                llm_metadata=llm_metadata,
                confidence=ConfidenceScore(
                    score=raw_result.get("confidence", {}).get("score", 0.0),
                    reason=raw_result.get("confidence", {}).get("reason", "Unknown"),
                )
            )

            logger.info("Successfully analyzed performance finding", extra={
                "query_id": snapshot.query_id,
                "latency_ms": latency_ms,
                "confidence_score": analysis_res.confidence.score
            })
            return analysis_res

        except Exception as e:
            logger.error("AnalysisResult parsing failed", extra={"error": str(e), "raw_payload": raw_result})
            raise LLMValidationError(f"Could not reconstruct valid AnalysisResult from LLM output: {e}")
