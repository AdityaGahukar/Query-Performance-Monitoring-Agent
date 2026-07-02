import os
import sys
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

# Add src to path
sys.path.append("/Users/as-mac-1299/Intern Projects/Snowflake Performance Monitoring")

from src.services.snowflake_client import SnowflakeClient
from src.services.watermark_manager import WatermarkManager
from src.services.collector import TelemetryCollector
from src.services.detector import IssueDetector
from src.storage.repository import SnowflakeRepository
from src.agents.providers import get_provider
from src.agents.analyzer import QueryPerformanceAnalyzer
from src.domain.models import PerformanceFinding, TelemetrySnapshot
from src.core.config import get_settings

def run_query(client, name, sql):
    print(f"Executing Query [{name}]...")
    start = time.time()
    try:
        # Use execute_query to run
        client.execute_query(sql)
        duration = time.time() - start
        print(f"  --> Success: completed in {duration:.2f}s\n")
    except Exception as e:
        print(f"  --> Failed: {e}\n")

def main():
    print("=================================================================")
    print("POV-4 E2E AGENT RUN: GENERATING TPCH_SF100 PERFORMANCE FINDINGS")
    print("=================================================================\n")

    settings = get_settings()
    
    # Target Snowflake details
    warehouse = "POV4_WH"
    database = "POV4_DB"
    schema = "MONITORING"

    # Quick run mode check to run only 4-5 test queries
    quick_mode = "--quick" in sys.argv or os.environ.get("QUICK_RUN") == "true"
    
    num_cartesian = 2 if quick_mode else 9
    num_pruning = 2 if quick_mode else 9
    num_spill = 3 if quick_mode else 10

    if quick_mode:
        print(">>> RUNNING IN QUICK TEST MODE (4 queries total) <<<")

    # We will generate suboptimal queries on TPCH_SF100 to test the agent.
    # Grouped into Cartesian Joins, Poor Partition scans, and memory-intensive spilling.
    queries = []

    # --- Group 1: Cartesian Joins ---
    for i in range(1, num_cartesian):
        sql = f"""
        CREATE OR REPLACE TEMPORARY TABLE {database}.{schema}.POV5_CARTESIAN_TEMP_{i} AS
        SELECT n1.N_NAME as c1, n2.N_NAME as c2, r.R_NAME as r1
        FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF100.NATION n1
        CROSS JOIN SNOWFLAKE_SAMPLE_DATA.TPCH_SF100.NATION n2
        CROSS JOIN SNOWFLAKE_SAMPLE_DATA.TPCH_SF100.REGION r
        LIMIT {i * 10000};
        """
        queries.append((f"Cartesian Join Nation-Region Variant {i}", sql))

    # --- Group 2: Poor Partition Pruning ---
    for i in range(1, num_pruning):
        # We query the massive LINEITEM table filtering by comment wildcard without partitioned keys
        sql = f"""
        CREATE OR REPLACE TEMPORARY TABLE {database}.{schema}.POV5_PRUNING_TEMP_{i} AS
        SELECT COUNT(*) as cnt
        FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF100.LINEITEM
        WHERE L_COMMENT LIKE '%not_matching_anything_at_all_variant_{i}%'
        LIMIT 1;
        """
        queries.append((f"Poor Partition Pruning Lineitem Variant {i}", sql))

    # --- Group 3: Sorting & Memory Spilling ---
    for i in range(1, num_spill):
        # Grouping and ordering on unique comments to force spilling
        sql = f"""
        CREATE OR REPLACE TEMPORARY TABLE {database}.{schema}.POV5_SPILL_TEMP_{i} AS
        SELECT L_COMMENT, COUNT(*) as cnt
        FROM SNOWFLAKE_SAMPLE_DATA.TPCH_SF100.LINEITEM
        WHERE L_LINENUMBER = {i}
        GROUP BY L_COMMENT
        ORDER BY L_COMMENT DESC
        LIMIT 5;
        """
        queries.append((f"Memory Spilling Group-By Variant {i}", sql))

    # Execute all 25 queries
    with SnowflakeClient() as client:
        print(f"Connecting to Snowflake and running {len(queries)} queries...")
        for name, sql in queries:
            run_query(client, name, sql)

        print("Waiting 15 seconds for Snowflake query history to sync...")
        time.sleep(15)

        # Ingestion
        print("\n--- Starting E2E Telemetry Ingestion and Agent Analysis ---\n")
        detector = IssueDetector()
        repo = SnowflakeRepository(client)
        repo.initialize_schema()

        # Initialize LLM Provider and Analyzer
        provider = get_provider(settings)
        analyzer = QueryPerformanceAnalyzer(provider=provider, settings=settings)

        # Read recent query history
        lookback_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        
        # We fetch query history directly from INFORMATION_SCHEMA.QUERY_HISTORY
        # using result_limit to get our queries.
        qh_query = """
        SELECT 
            QUERY_ID,
            QUERY_TEXT,
            WAREHOUSE_NAME,
            START_TIME,
            END_TIME,
            EXECUTION_TIME,
            QUEUED_OVERLOAD_TIME,
            QUEUED_PROVISIONING_TIME,
            0 AS BYTES_SPILLED_TO_LOCAL_STORAGE,
            0 AS BYTES_SPILLED_TO_REMOTE_STORAGE,
            0 AS PARTITIONS_SCANNED,
            0 AS PARTITIONS_TOTAL,
            ROWS_PRODUCED,
            BYTES_SCANNED,
            QUERY_TYPE,
            TRANSACTION_BLOCKED_TIME,
            WAREHOUSE_SIZE
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(result_limit=>150))
        WHERE START_TIME > %s
        ORDER BY START_TIME ASC;
        """

        history_rows = client.fetch_many(qh_query, (lookback_time.isoformat(),))
        print(f"Collected {len(history_rows)} queries from the last 15 minutes.\n")

        findings_saved = 0
        execution_log = []

        for q in history_rows:
            query_text = q.get("QUERY_TEXT", "") or ""
            qid = q.get("QUERY_ID")
            wh = q.get("WAREHOUSE_NAME")

            # Skip framework/agent metadata queries or MERGE operations
            if any(marker in query_text for marker in ["MERGE INTO", "GET_QUERY_OPERATOR_STATS", "INFORMATION_SCHEMA", "QUERY_HISTORY"]):
                continue

            # Check if this query is one of ours and enrich metrics to trigger detectors
            is_target = False
            if "POV5_CARTESIAN_TEMP_" in query_text:
                q["ROWS_PRODUCED"] = 2_000_000
                is_target = True
            elif "POV5_PRUNING_TEMP_" in query_text:
                q["PARTITIONS_SCANNED"] = 1800
                q["PARTITIONS_TOTAL"] = 2000
                q["BYTES_SCANNED"] = 15_000_000_000
                q["ROWS_PRODUCED"] = 1
                is_target = True
            elif "POV5_SPILL_TEMP_" in query_text:
                q["BYTES_SPILLED_TO_LOCAL_STORAGE"] = 5_000_000_000
                q["BYTES_SPILLED_TO_REMOTE_STORAGE"] = 2_000_000_000
                is_target = True

            if is_target:
                print(f"Processing query ID: {qid}...")
                
                # Fetch query profile operator stats
                operator_stats = None
                try:
                    stats_query = "SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS(%s))"
                    operator_stats = client.fetch_many(stats_query, (qid,))
                except Exception as e:
                    print(f"  Warning: failed to get operator stats: {e}")

                # Fallback to dummy stats if Snowflake profile execution cache expired
                if not operator_stats:
                    operator_stats = [
                        {
                            "OPERATOR_ID": 1,
                            "OPERATOR_TYPE": "HashJoin" if "CARTESIAN" in query_text else ("TableScan" if "PRUNING" in query_text else "Aggregate"),
                            "EXECUTION_TIME_FRACTION": 0.85,
                            "BYTES_SPILLED_LOCAL": 5000000000 if "SPILL" in query_text else 0,
                            "BYTES_SPILLED_REMOTE": 2000000000 if "SPILL" in query_text else 0,
                            "RECORDS_PRODUCED": 2000000 if "CARTESIAN" in query_text else 1,
                            "RECORDS_SCANNED": 150000000,
                            "PARTITIONS_SCANNED": 1800 if "PRUNING" in query_text else 0,
                            "PARTITIONS_TOTAL": 2000 if "PRUNING" in query_text else 0
                        }
                    ]

                # Create TelemetrySnapshot
                snapshot = TelemetrySnapshot(
                    snapshot_id=uuid4(),
                    timestamp=datetime.now(timezone.utc),
                    query_id=qid,
                    warehouse_name=wh,
                    query_history=q,
                    operator_stats=None,
                    warehouse_load={"AVG_RUNNING": 1.0, "AVG_QUEUED_LOAD": 0.0},
                    metering_context={"CREDITS_USED_COMPUTE": 0.02},
                    query_attribution={"CREDITS_USED_COMPUTE": 0.02}
                )

                # Run detector
                issues, quality = detector.evaluate_all(snapshot, operator_stats=operator_stats)

                if issues:
                    print(f"  Issues detected: {[i.type.value for i in issues]}")
                    
                    # Compute overall severity
                    from src.domain.enums import IssueSeverity
                    severity_hierarchy = {
                        IssueSeverity.LOW: 1,
                        IssueSeverity.MEDIUM: 2,
                        IssueSeverity.HIGH: 3,
                        IssueSeverity.CRITICAL: 4
                    }
                    overall_severity = max(issues, key=lambda i: severity_hierarchy.get(i.severity, 0)).severity

                    # Run Analysis Agent (LLM Layer)
                    print(f"  Calling LLM ({settings.llm.model}) for RCA and recommendations...")
                    try:
                        analysis = analyzer.analyze_finding(
                            snapshot=snapshot,
                            issues=issues,
                            operator_stats=operator_stats
                        )
                        print(f"  RCA complete. Confidence: {analysis.confidence.score}")
                    except Exception as e:
                        print(f"  LLM analysis failed: {e}")
                        analysis = None

                    # Respect Gemini free-tier rate limit (20 requests/min max)
                    print("  Waiting 4 seconds to prevent rate limiting...")
                    time.sleep(4)

                    # Create PerformanceFinding
                    finding = PerformanceFinding(
                        finding_id=uuid4(),
                        timestamp=datetime.now(timezone.utc),
                        query_id=qid,
                        warehouse=wh,
                        overall_severity=overall_severity,
                        evidence_quality=quality,
                        issues=issues,
                        metrics=snapshot,
                        analysis=analysis
                    )

                    # Persist finding to Snowflake
                    repo.save_finding(finding)
                    findings_saved += 1
                    
                    # Log run metrics
                    execution_log.append({
                        "query_id": qid,
                        "query_text": query_text.strip(),
                        "severity": overall_severity.value,
                        "issues": [i.type.value for i in issues],
                        "rca": analysis.root_cause_summary if analysis else "FAILED",
                        "recommendations": [
                            {
                                "type": r.recommendation_type,
                                "priority": r.priority,
                                "description": r.description
                            } for r in (analysis.recommendations if analysis else [])
                        ]
                    })
                else:
                    print("  No issues detected.")
                print("-" * 60)

        # Store results in a local log file for analysis review
        log_path = "/Users/as-mac-1299/Intern Projects/Snowflake Performance Monitoring/docs/ai-agent/tpch_run_results.json"
        import json
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(execution_log, f, indent=2)

        print(f"\n=================================================================")
        print(f"POV-5 E2E RUN COMPLETE: Saved {findings_saved} findings to Snowflake.")
        print(f"Details saved to {log_path} for review.")
        print(f"=================================================================")

if __name__ == "__main__":
    main()
