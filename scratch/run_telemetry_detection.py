"""
One-off script to run incremental telemetry collection and issue detection.
Connects to Snowflake, reads telemetry using the watermark, evaluates rules,
and stores detected findings.
"""
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

# Add src to path
sys.path.append("/Users/as-mac-1299/Intern Projects/Snowflake Performance Monitoring")

from src.services.snowflake_client import SnowflakeClient
from src.services.watermark_manager import WatermarkManager
from src.services.collector import TelemetryCollector
from src.services.detector import IssueDetector
from src.storage.repository import SnowflakeRepository
from src.domain.models import PerformanceFinding, TelemetrySnapshot
from src.domain.enums import IssueSeverity
from src.core.config import get_settings
from src.agents.providers import get_provider
from src.agents.analyzer import QueryPerformanceAnalyzer

def main():
    print("=================================================================")
    print("POV-4: REAL TELEMETRY COLLECTION & DETERMINISTIC RULE ENGINE")
    print("=================================================================\n")

    with SnowflakeClient() as client:
        # Initialize components
        repo = SnowflakeRepository(client)
        repo.initialize_schema()  # creates tables if not present
        
        watermark_manager = WatermarkManager(client)
        collector = TelemetryCollector(client, watermark_manager)
        detector = IssueDetector()

        # Initialize LLM components for Phase 5 RCA (NVIDIA AI Endpoints)
        settings = get_settings()
        provider = None
        analyzer = None
        if settings.llm.api_key:
            try:
                provider = get_provider(settings)
                analyzer = QueryPerformanceAnalyzer(provider, settings)
                print(f"LLM Analyzer successfully initialized using provider: {settings.llm.provider}")
            except Exception as e:
                print(f"Warning: Failed to initialize LLM Provider: {e}")

        # Print current watermarks
        print("Checking watermarks...")
        qh_watermark = watermark_manager.get_watermark("QUERY_HISTORY")
        print(f"Current QUERY_HISTORY watermark: {qh_watermark.isoformat()}\n")

        # Ingestion loop to process multiple batches to catch up history
        print("Ingesting query history and warehouse load telemetry (in batches of 1000)...")
        total_evaluated = 0
        findings_saved = 0
        batches_run = 0
        max_batches = 10  # Evaluate up to 10,000 queries sequentially to reach findings

        while batches_run < max_batches:
            snapshots = collector.collect_snapshots()
            if not snapshots:
                break
                
            print(f"Batch {batches_run + 1}: Collected {len(snapshots)} new query history snapshots.")
            
            for snapshot in snapshots:
                qid = snapshot.query_id
                query_text = snapshot.query_history.get("QUERY_TEXT", "").strip()
                
                # 1. Run deterministic rule engine
                operator_stats = None
                issues, quality = detector.evaluate_all(snapshot, operator_stats=operator_stats)
                
                if issues:
                    print(f"[*] Potential issue flagged for Query ID: {qid}")
                    print(f"    SQL: {query_text[:120]}...")
                    print(f"    Triggered Rules (Initial): {[i.type.value for i in issues]}")
                    print(f"    Evidence Quality: {quality.value}")
                    
                    # Check if we need plan-level profile stats
                    stage1_expensive_join = (
                        snapshot.query_history.get("ROWS_PRODUCED", 0) or 0
                    ) > 10_000_000 or (snapshot.query_history.get("BYTES_SCANNED", 0) or 0) > 107_374_182_400
                    stage1_cartesian = (snapshot.query_history.get("ROWS_PRODUCED", 0) or 0) > 1_000_000
                    
                    if stage1_expensive_join or stage1_cartesian:
                        print(f"    --> Lazy-fetching execution profile operator stats for Query ID: {qid}")
                        try:
                            operator_stats = collector.get_query_operator_stats(qid)
                            issues, quality = detector.evaluate_all(snapshot, operator_stats=operator_stats)
                            print(f"    Triggered Rules (Refined): {[i.type.value for i in issues]}")
                        except Exception as e:
                            print(f"    Warning: Failed to fetch operator stats: {e}")
                    
                    # 2. Run LLM root cause analysis (Phase 5)
                    analysis = None
                    if analyzer:
                        print(f"    --> Invoking LLM Performance Analysis for Query ID: {qid}...")
                        try:
                            analysis_res = analyzer.analyze_finding(snapshot, issues, operator_stats=operator_stats)
                            analysis = analysis_res
                            print(f"    [+] Root Cause: {analysis.root_cause[:120]}...")
                            print(f"    [+] Recommendation: {analysis.recommendations[0][:120]}...")
                        except Exception as e:
                            print(f"    Warning: LLM Analysis execution failed: {e}")
                    
                    # Determine overall severity
                    severity_hierarchy = {
                        IssueSeverity.LOW: 1,
                        IssueSeverity.MEDIUM: 2,
                        IssueSeverity.HIGH: 3,
                        IssueSeverity.CRITICAL: 4
                    }
                    overall_severity = max(issues, key=lambda i: severity_hierarchy.get(i.severity, 0)).severity
                    
                    # Package finding
                    finding = PerformanceFinding(
                        finding_id=uuid4(),
                        timestamp=datetime.now(timezone.utc),
                        query_id=qid,
                        warehouse=snapshot.warehouse_name,
                        overall_severity=overall_severity,
                        evidence_quality=quality,
                        issues=issues,
                        metrics=snapshot,
                        analysis=analysis
                    )
                    
                    # Save finding to Snowflake
                    repo.save_finding(finding)
                    findings_saved += 1
                    print(f"    --> Saved finding to Snowflake: {repo.settings.findings_table}")
                    print("-" * 60)
            
            total_evaluated += len(snapshots)
            batches_run += 1
                
        print(f"\nExecution complete. Evaluated {total_evaluated} queries across {batches_run} batches, and saved {findings_saved} performance findings.")

if __name__ == "__main__":
    main()
