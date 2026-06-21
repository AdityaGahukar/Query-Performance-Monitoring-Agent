import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from src.core.logging import get_logger
from src.domain.models import TelemetrySnapshot
from src.services.snowflake_client import SnowflakeClient
from src.services.watermark_manager import WatermarkManager

logger = get_logger(__name__)

SQL_DIR = Path(__file__).parent / "sql"


class TelemetryCollector:
    """
    Collects telemetry from Snowflake incrementally, managing watermarks,
    and maps the raw data into TelemetrySnapshot domain models.
    """

    def __init__(self, client: SnowflakeClient, watermark_manager: WatermarkManager):
        self.client = client
        self.wm = watermark_manager

    def _read_sql(self, filename: str) -> str:
        with open(SQL_DIR / filename, "r") as f:
            return f.read()

    def _execute_incremental(self, source_name: str, sql_file: str) -> List[Dict[str, Any]]:
        """Helper to run an incremental query and update the watermark."""
        watermark = self.wm.get_watermark(source_name)
        query = self._read_sql(sql_file)
        
        results = self.client.fetch_many(query, {"start_time": watermark})
        if results:
            max_time = max(row["START_TIME"] for row in results if row.get("START_TIME"))
            if max_time:
                # Ensure UTC awareness
                if max_time.tzinfo is None:
                    max_time = max_time.replace(tzinfo=timezone.utc)
                self.wm.update_watermark(source_name, max_time)
        return results

    def collect_query_history(self) -> List[Dict[str, Any]]:
        return self._execute_incremental("QUERY_HISTORY", "query_history.sql")

    def collect_warehouse_load_history(self) -> List[Dict[str, Any]]:
        return self._execute_incremental("WAREHOUSE_LOAD_HISTORY", "warehouse_load_history.sql")

    def collect_metering_history(self) -> List[Dict[str, Any]]:
        return self._execute_incremental("METERING_HISTORY", "metering_history.sql")

    def collect_query_attribution_history(self) -> List[Dict[str, Any]]:
        return self._execute_incremental("QUERY_ATTRIBUTION_HISTORY", "query_attribution_history.sql")

    def get_query_operator_stats(self, query_id: str) -> List[Dict[str, Any]]:
        """
        Lazy retrieval of operator stats.
        This is explicitly decoupled from standard telemetry polling.
        """
        query = self._read_sql("get_operator_stats.sql")
        return self.client.fetch_many(query, {"query_id": query_id})

    def collect_snapshots(self) -> List[TelemetrySnapshot]:
        """
        Orchestrates collection across all telemetry sources and maps them
        into TelemetrySnapshot domain models.

        Note: For Phase 2 MVP, we simply pull the latest from all streams 
        and align them in memory.
        """
        queries = self.collect_query_history()
        
        if not queries:
            logger.info("No new queries found since last watermark.")
            return []

        # Fetch supporting metrics
        load_history = self.collect_warehouse_load_history()
        metering = self.collect_metering_history()
        attribution = self.collect_query_attribution_history()

        # Build fast lookup indexes
        attr_idx = {r["QUERY_ID"]: r for r in attribution if "QUERY_ID" in r}

        snapshots = []
        for q in queries:
            qid = q.get("QUERY_ID", "UNKNOWN")
            wh = q.get("WAREHOUSE_NAME", "UNKNOWN")
            
            # Simple best-effort matching for MVP. 
            # In V2, we might do exact time-bucket alignment.
            q_attr = attr_idx.get(qid, {})
            
            q_load = next((r for r in load_history if r.get("WAREHOUSE_NAME") == wh), {})
            q_metering = next((r for r in metering if r.get("WAREHOUSE_NAME") == wh), {})

            snapshot = TelemetrySnapshot(
                snapshot_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                query_id=qid,
                warehouse_name=wh,
                query_history=q,
                query_profile=None,  # Intentionally omitted (Lazy fetch only)
                warehouse_load=q_load,
                metering_context=q_metering,
                query_attribution=q_attr,
            )
            snapshots.append(snapshot)

        logger.info("Successfully constructed %d TelemetrySnapshots", len(snapshots))
        return snapshots
