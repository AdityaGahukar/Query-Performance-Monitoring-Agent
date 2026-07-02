import sys
import os
from uuid import uuid4
from datetime import datetime, timezone

# 1. Setup sandbox environment variables to satisfy Pydantic validation constraints
os.environ["SNOWFLAKE_ACCOUNT"] = "stored_procedure"
os.environ["SNOWFLAKE_USER"] = "stored_procedure"
os.environ["SNOWFLAKE_PASSWORD"] = "stored_procedure"
os.environ["SNOWFLAKE_WAREHOUSE"] = "stored_procedure"
os.environ["SNOWFLAKE_DATABASE"] = "POV4_DB"
os.environ["SNOWFLAKE_SCHEMA"] = "MONITORING"
os.environ["SNOWFLAKE_ROLE"] = "stored_procedure"
os.environ["LLM_PROVIDER"] = "nvidia"
os.environ["LLM_API_KEY"] = "stored_procedure_dummy_key"

# 2. Add our source imports path (relative to the Snowflake sandbox imports directory)
# Snowflake extracts uploaded stages (like src.zip) to the directory specified by sys._MEIPASS
if hasattr(sys, "_MEIPASS"):
    sys.path.append(os.path.join(sys._MEIPASS, "src.zip"))
else:
    # Local verification fallback
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.config import get_settings
from src.services.snowflake_client import SnowflakeClient
from src.services.watermark_manager import WatermarkManager
from src.services.collector import TelemetryCollector
from src.services.detector import IssueDetector
from src.storage.repository import SnowflakeRepository
from src.domain.models import PerformanceFinding, TelemetrySnapshot
from src.domain.enums import IssueSeverity

def run_detection(session):
    """
    Stored Procedure entrypoint handler.
    Snowflake automatically passes the active Snowpark 'session' object.
    """
    # Extract current active database and schema names from session or use defaults
    db = session.get_current_database() or "POV4_DB"
    schema = session.get_current_schema() or "MONITORING"
    os.environ["SNOWFLAKE_DATABASE"] = db.strip('"')
    os.environ["SNOWFLAKE_SCHEMA"] = schema.strip('"')

    # Fetch Nvidia API key from Snowflake secrets if configured
    secret_status = "Not loaded"
    try:
        import _snowflake
        api_key = _snowflake.get_generic_secret_string('NVIDIA_API_KEY_SECRET')
        if api_key:
            os.environ["LLM_API_KEY"] = api_key
            secret_status = "Loaded from Secret"
    except Exception as secret_err:
        secret_status = f"Bypassed/Error: {str(secret_err)}"

    # Grab the underlying python database connection from Snowpark session
    raw_connection = session.connection
    
    # Wrap it in our customized SnowflakeClient
    with SnowflakeClient(connection=raw_connection) as client:
        # Initialize findings and watermark tables if not present
        repo = SnowflakeRepository(client)
        repo.initialize_schema()
        
        watermark_manager = WatermarkManager(client)
        collector = TelemetryCollector(client, watermark_manager)
        detector = IssueDetector()

        # Initialize LLM analyzer components if key is loaded
        settings = get_settings()
        analyzer = None
        llm_status = "LLM Engine Paused (No Key)"
        
        if settings.llm.api_key and settings.llm.api_key != "stored_procedure_dummy_key":
            try:
                from src.agents.providers import get_provider
                from src.agents.analyzer import QueryPerformanceAnalyzer
                provider = get_provider(settings)
                analyzer = QueryPerformanceAnalyzer(provider, settings)
                llm_status = f"Active ({settings.llm.model})"
            except Exception as init_err:
                llm_status = f"Initialization Error: {str(init_err)}"
        
        # Diagnostics: run direct query to check if we can read the watermark table
        try:
            row = client.fetch_one(
                "SELECT LAST_PROCESSED_TIMESTAMP FROM POV4_WATERMARKS WHERE SOURCE_NAME = %s",
                ("QUERY_HISTORY",)
            )
            direct_result = f"Row: {row}"
        except Exception as ex:
            direct_result = f"ERROR: {type(ex).__name__}: {str(ex)}"

        # 1. Incremental Ingestion Batch Loop
        total_evaluated = 0
        total_findings = 0
        batches_run = 0
        max_batches = 10 # Process up to 10,000 queries to catch up history in a single execution

        qh_wm_before = watermark_manager.get_watermark("QUERY_HISTORY")

        while batches_run < max_batches:
            snapshots = collector.collect_snapshots()
            if not snapshots:
                break

            for snapshot in snapshots:
                qid = snapshot.query_id
                
                # 2. Evaluate rules (Phase 1-4 validation query checks)
                operator_stats = None
                issues, quality = detector.evaluate_all(snapshot, operator_stats=operator_stats)
                
                if issues:
                    # check if we need plan-level profile stats (CartesianJoin or ExpensiveJoin)
                    rows = snapshot.query_history.get("ROWS_PRODUCED", 0) or 0
                    bytes_scanned = snapshot.query_history.get("BYTES_SCANNED", 0) or 0
                    
                    # If query is large/heavy, lazy-fetch profile operator stats
                    if rows > 1_000_000 or bytes_scanned > 107_374_182_400:
                        try:
                            operator_stats = collector.get_query_operator_stats(qid)
                            issues, quality = detector.evaluate_all(snapshot, operator_stats=operator_stats)
                        except Exception:
                            pass
                    
                    # Determine highest severity among triggered rules
                    severity_hierarchy = {
                        IssueSeverity.LOW: 1,
                        IssueSeverity.MEDIUM: 2,
                        IssueSeverity.HIGH: 3,
                        IssueSeverity.CRITICAL: 4
                    }
                    overall_severity = max(issues, key=lambda i: severity_hierarchy.get(i.severity, 0)).severity
                    
                    # 3. Call LLM Analyzer for RCA and Recommendations
                    analysis = None
                    if analyzer:
                        try:
                            analysis = analyzer.analyze_finding(
                                snapshot=snapshot,
                                issues=issues,
                                operator_stats=operator_stats
                            )
                        except Exception as llm_err:
                            # Contain LLM failures so they don't break the collection pipeline
                            pass

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
                    
                    # Save finding to Snowflake tables
                    repo.save_finding(finding)
                    total_findings += 1

            total_evaluated += len(snapshots)
            batches_run += 1

        qh_wm_after = watermark_manager.get_watermark("QUERY_HISTORY")
        return (
            f"Success: Evaluated {total_evaluated} queries across {batches_run} batches, "
            f"saved {total_findings} findings to Snowflake. "
            f"Secret Status: {secret_status}, LLM Status: {llm_status}. "
            f"Diagnostics: QH_WM_BEFORE={qh_wm_before}, QH_WM_AFTER={qh_wm_after}. "
            f"Direct test: {direct_result}"
        )
