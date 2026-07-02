"""
POV-4: LLM Findings Enrichment Daemon/Script.

Used as a fallback for Snowflake Trial Accounts where External Access Integration
is disabled.

This script:
1. Connects to Snowflake using local credentials in `.env`.
2. Queries the findings table for rows where the LLM `ANALYSIS` field is NULL
   and filters by a recent timeframe (e.g. last 24 hours) and limit.
3. Reconstructs the finding and telemetry snapshot models.
4. Invokes the local Nvidia AI Endpoints analyzer to generate the RCA and recommendations.
5. Saves the enriched findings back to Snowflake using a MERGE query.
"""

import sys
import os
import json
import argparse
from uuid import UUID
from datetime import datetime, timezone
import dotenv

# Force add project root to python path to prevent ModuleNotFoundError
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

dotenv.load_dotenv()

from src.core.config import get_settings
from src.services.snowflake_client import SnowflakeClient
from src.storage.repository import SnowflakeRepository
from src.agents.providers import get_provider
from src.agents.analyzer import QueryPerformanceAnalyzer
from src.domain.models import PerformanceFinding, TelemetrySnapshot, DetectedIssue
from src.domain.enums import IssueSeverity, EvidenceQuality

def enrich_findings(hours: int = 24, limit: int = 50):
    print("=================================================================")
    print("POV-4 HYBRID AGENT: ENRICHING NATIVE FINDINGS WITH LOCAL LLM")
    print(f"Filters: Ingested in last {hours} hours | Max count: {limit}")
    print("=================================================================")

    settings = get_settings()
    
    # 1. Initialize local LLM components
    if not settings.llm.api_key:
        print("Error: LLM_API_KEY must be set in your .env file to run local enrichment.")
        return

    try:
        provider = get_provider(settings)
        analyzer = QueryPerformanceAnalyzer(provider, settings)
        print(f"LLM Analyzer initialized successfully using model: {settings.llm.model}")
    except Exception as llm_err:
        print(f"Error: Failed to initialize local LLM analyzer: {llm_err}")
        return

    # 2. Connect to Snowflake and fetch unenriched findings
    print("Connecting to Snowflake...")
    with SnowflakeClient() as client:
        repo = SnowflakeRepository(client)
        
        # Query findings where LLM Analysis is NULL, matching the timeframe and limit
        query = f"""
        SELECT 
            FINDING_ID, TIMESTAMP, QUERY_ID, WAREHOUSE, OVERALL_SEVERITY, EVIDENCE_QUALITY, 
            TO_JSON(ISSUES) as ISSUES_JSON, TO_JSON(METRICS) as METRICS_JSON
        FROM {settings.storage.findings_table}
        WHERE (ANALYSIS IS NULL OR ANALYSIS:root_cause_summary IS NULL)
          AND TIMESTAMP >= DATEADD(hour, -%s, CURRENT_TIMESTAMP())
        ORDER BY TIMESTAMP DESC
        LIMIT %s
        """
        
        try:
            rows = client.fetch_many(query, (hours, limit))
        except Exception as sql_err:
            print(f"Error querying findings table: {sql_err}")
            return
            
        if not rows:
            print(f"No unenriched findings from the last {hours} hours found in Snowflake.")
            return
            
        print(f"Found {len(rows)} recent findings requiring LLM analysis. Processing...")
        
        for row in rows:
            fid = row["FINDING_ID"]
            qid = row["QUERY_ID"]
            print(f"\nProcessing Finding {fid} (Query ID: {qid})...")
            
            # Reconstruct models from JSON columns
            try:
                issues_list = json.loads(row["ISSUES_JSON"])
                metrics_dict = json.loads(row["METRICS_JSON"])
                
                issues = [DetectedIssue(**issue) for issue in issues_list]
                snapshot = TelemetrySnapshot(**metrics_dict)
                
                ts = row["TIMESTAMP"]
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception as parse_err:
                print(f"  Warning: Failed to reconstruct models for finding {fid}: {parse_err}")
                continue
                
            # Run LLM root cause analysis locally
            print(f"  Calling LLM ({settings.llm.model}) for local analysis...")
            try:
                analysis = analyzer.analyze_finding(
                    snapshot=snapshot,
                    issues=issues,
                    operator_stats=snapshot.operator_stats
                )
                print(f"  Analysis complete. Root Cause: {analysis.root_cause_summary}")
            except Exception as llm_err:
                print(f"  Warning: LLM analysis failed for query {qid}: {llm_err}")
                continue
                
            # Re-package finding with the new analysis
            finding = PerformanceFinding(
                finding_id=UUID(fid),
                timestamp=ts,
                query_id=qid,
                warehouse=row["WAREHOUSE"],
                overall_severity=IssueSeverity(row["OVERALL_SEVERITY"]),
                evidence_quality=EvidenceQuality(row["EVIDENCE_QUALITY"]),
                issues=issues,
                metrics=snapshot,
                analysis=analysis
            )
            
            # Save enriched finding back to Snowflake
            try:
                repo.save_finding(finding)
                print(f"  Successfully saved enriched diagnostics to Snowflake for finding {fid}.")
            except Exception as save_err:
                print(f"  Error updating finding {fid} in Snowflake: {save_err}")
                
    print("\n=================================================================")
    print("ENRICHMENT PROCESS RUN COMPLETE")
    print("=================================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enrich Snowflake findings with local LLM diagnostics.")
    parser.add_argument("--hours", type=int, default=24, help="Only enrich findings detected in the last N hours (default: 24).")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of findings to enrich in this run (default: 50).")
    args = parser.parse_args()
    
    enrich_findings(hours=args.hours, limit=args.limit)
