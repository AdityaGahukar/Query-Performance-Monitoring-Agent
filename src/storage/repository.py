import json
import os
from datetime import timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from src.core.config import get_settings
from src.core.logging import get_logger
from src.domain.enums import EvidenceQuality, IssueSeverity, AlertDestination, AlertStatus
from src.domain.models import AlertEvent, AnalysisResult, DetectedIssue, PerformanceFinding, TelemetrySnapshot
from src.services.snowflake_client import SnowflakeClient

logger = get_logger(__name__)


class SnowflakeRepository:
    """
    Handles persistence of PerformanceFinding and AlertEvent models in Snowflake.
    """

    def __init__(self, client: SnowflakeClient):
        self.client = client
        self.settings = get_settings().storage

    def initialize_schema(self) -> None:
        """Reads and executes the DDL schema to ensure tables are created."""
        ddl_path = os.path.join(os.path.dirname(__file__), "ddl.sql")
        try:
            with open(ddl_path, "r") as f:
                ddl_sql = f.read()

            # Execute each DDL statement separately
            statements = ddl_sql.split(";")
            for stmt in statements:
                stmt_clean = stmt.strip()
                if stmt_clean:
                    # Resolve table names dynamically from settings if needed
                    # However, since config matches the default names in DDL, we execute directly
                    self.client.execute_query(stmt_clean)
            logger.info("Database schema initialized successfully.")
        except Exception as e:
            logger.error("Failed to initialize database schema", extra={"error": str(e)})
            raise

    def save_finding(self, finding: PerformanceFinding) -> None:
        """
        Saves or updates a PerformanceFinding in the Snowflake findings table.
        Uses MERGE to handle both insertion and inline updates of analysis.
        """
        issues_json = json.dumps([issue.model_dump() for issue in finding.issues], default=str)
        metrics_json = finding.metrics.model_dump_json()
        analysis_json = finding.analysis.model_dump_json() if finding.analysis else None

        query = f"""
        MERGE INTO {self.settings.findings_table} AS target
        USING (
            SELECT 
                %s AS FINDING_ID, 
                %s::TIMESTAMP_TZ AS TIMESTAMP, 
                %s AS QUERY_ID, 
                %s AS WAREHOUSE, 
                %s AS OVERALL_SEVERITY, 
                %s AS EVIDENCE_QUALITY, 
                PARSE_JSON(%s) AS ISSUES, 
                PARSE_JSON(%s) AS METRICS, 
                PARSE_JSON(%s) AS ANALYSIS
        ) AS source
        ON target.FINDING_ID = source.FINDING_ID
        WHEN MATCHED THEN
            UPDATE SET 
                target.TIMESTAMP = source.TIMESTAMP,
                target.OVERALL_SEVERITY = source.OVERALL_SEVERITY,
                target.EVIDENCE_QUALITY = source.EVIDENCE_QUALITY,
                target.ISSUES = source.ISSUES,
                target.METRICS = source.METRICS,
                target.ANALYSIS = source.ANALYSIS
        WHEN NOT MATCHED THEN
            INSERT (FINDING_ID, TIMESTAMP, QUERY_ID, WAREHOUSE, OVERALL_SEVERITY, EVIDENCE_QUALITY, ISSUES, METRICS, ANALYSIS)
            VALUES (source.FINDING_ID, source.TIMESTAMP, source.QUERY_ID, source.WAREHOUSE, source.OVERALL_SEVERITY, source.EVIDENCE_QUALITY, source.ISSUES, source.METRICS, source.ANALYSIS);
        """
        params = (
            str(finding.finding_id),
            finding.timestamp.isoformat(),
            finding.query_id,
            finding.warehouse,
            finding.overall_severity.value,
            finding.evidence_quality.value,
            issues_json,
            metrics_json,
            analysis_json,
        )
        self.client.execute_query(query, params)
        logger.debug("Successfully saved finding", extra={"finding_id": str(finding.finding_id)})

    def get_finding(self, finding_id: UUID) -> Optional[PerformanceFinding]:
        """
        Retrieves a PerformanceFinding from Snowflake by UUID.
        Reconstructs the nested Pydantic models.
        """
        query = f"""
        SELECT 
            FINDING_ID, TIMESTAMP, QUERY_ID, WAREHOUSE, OVERALL_SEVERITY, EVIDENCE_QUALITY, 
            TO_JSON(ISSUES) as ISSUES, TO_JSON(METRICS) as METRICS, TO_JSON(ANALYSIS) as ANALYSIS
        FROM {self.settings.findings_table}
        WHERE FINDING_ID = %s
        """
        row = self.client.fetch_one(query, (str(finding_id),))
        if not row:
            return None

        # Deserialise JSON columns
        issues_list = json.loads(row["ISSUES"])
        metrics_dict = json.loads(row["METRICS"])
        analysis_dict = json.loads(row["ANALYSIS"]) if row["ANALYSIS"] else None

        # Reconstruct submodels
        issues = [DetectedIssue(**issue) for issue in issues_list]
        metrics = TelemetrySnapshot(**metrics_dict)
        analysis = AnalysisResult(**analysis_dict) if analysis_dict else None

        # Ensure timestamp is UTC aware
        ts = row["TIMESTAMP"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        return PerformanceFinding(
            finding_id=UUID(row["FINDING_ID"]),
            timestamp=ts,
            query_id=row["QUERY_ID"],
            warehouse=row["WAREHOUSE"],
            overall_severity=IssueSeverity(row["OVERALL_SEVERITY"]),
            evidence_quality=EvidenceQuality(row["EVIDENCE_QUALITY"]),
            issues=issues,
            metrics=metrics,
            analysis=analysis,
        )

    def save_alert_event(self, event: AlertEvent) -> None:
        """
        Saves or updates an AlertEvent (e.g. DLQ retry status) in Snowflake.
        """
        query = f"""
        MERGE INTO {self.settings.dlq_table} AS target
        USING (
            SELECT 
                %s AS ALERT_ID, 
                %s AS FINDING_REFERENCE, 
                %s AS DESTINATION, 
                %s AS STATUS, 
                %s::TIMESTAMP_TZ AS DELIVERY_TIMESTAMP
        ) AS source
        ON target.ALERT_ID = source.ALERT_ID
        WHEN MATCHED THEN
            UPDATE SET 
                target.STATUS = source.STATUS,
                target.DELIVERY_TIMESTAMP = source.DELIVERY_TIMESTAMP
        WHEN NOT MATCHED THEN
            INSERT (ALERT_ID, FINDING_REFERENCE, DESTINATION, STATUS, DELIVERY_TIMESTAMP)
            VALUES (source.ALERT_ID, source.FINDING_REFERENCE, source.DESTINATION, source.STATUS, source.DELIVERY_TIMESTAMP);
        """
        params = (
            str(event.alert_id),
            str(event.finding_reference),
            event.destination.value,
            event.status.value,
            event.delivery_timestamp.isoformat() if event.delivery_timestamp else None,
        )
        self.client.execute_query(query, params)
        logger.debug("Successfully saved alert event", extra={"alert_id": str(event.alert_id)})

    def get_alert_event(self, alert_id: UUID) -> Optional[AlertEvent]:
        """Retrieves an AlertEvent from the DLQ table by UUID."""
        query = f"""
        SELECT ALERT_ID, FINDING_REFERENCE, DESTINATION, STATUS, DELIVERY_TIMESTAMP
        FROM {self.settings.dlq_table}
        WHERE ALERT_ID = %s
        """
        row = self.client.fetch_one(query, (str(alert_id),))
        if not row:
            return None

        ts = row["DELIVERY_TIMESTAMP"]
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        return AlertEvent(
            alert_id=UUID(row["ALERT_ID"]),
            finding_reference=UUID(row["FINDING_REFERENCE"]),
            destination=AlertDestination(row["DESTINATION"]),
            status=AlertStatus(row["STATUS"]),
            delivery_timestamp=ts,
        )
