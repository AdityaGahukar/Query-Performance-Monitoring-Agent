"""
Watermark management for incremental telemetry collection.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from src.core.config import get_settings
from src.core.logging import get_logger
from src.services.snowflake_client import SnowflakeClient

logger = get_logger(__name__)

# Fallback watermark: collect up to 1 hour of history if no watermark exists
DEFAULT_LOOKBACK_HOURS = 1


class WatermarkManager:
    """
    Manages watermarks for telemetry sources to ensure incremental collection.
    Supports reading/writing to the Snowflake STORAGE_WATERMARKS_TABLE with a local file fallback.
    """

    def __init__(self, client: Optional[SnowflakeClient] = None, state_file: str = ".watermarks.json"):
        self.client = client
        self.state_file = state_file
        self.settings = get_settings().storage
        self._watermarks: Dict[str, datetime] = {}
        
        # If client is not available, load initial watermarks from file
        if not self.client:
            self._watermarks = self._load_file()

    def _load_file(self) -> Dict[str, datetime]:
        """Load watermarks from local JSON file."""
        if not os.path.exists(self.state_file):
            return {}
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
                return {k: datetime.fromisoformat(v) for k, v in data.items()}
        except Exception as e:
            logger.error("Failed to load watermarks from file", extra={"error": str(e)})
            return {}

    def _save_file(self) -> None:
        """Save watermarks to local JSON file."""
        try:
            with open(self.state_file, "w") as f:
                data = {k: v.isoformat() for k, v in self._watermarks.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save watermarks to file", extra={"error": str(e)})

    def get_watermark(self, source: str) -> datetime:
        """
        Retrieve the current watermark for a given telemetry source.
        Queries Snowflake if a client is active; otherwise falls back to memory/file.
        """
        if self.client:
            try:
                query = f"""
                SELECT LAST_PROCESSED_TIMESTAMP 
                FROM {self.settings.watermarks_table} 
                WHERE SOURCE_NAME = %s
                """
                row = self.client.fetch_one(query, (source,))
                if row and row.get("LAST_PROCESSED_TIMESTAMP"):
                    ts = row["LAST_PROCESSED_TIMESTAMP"]
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    self._watermarks[source] = ts
                    return ts
            except Exception as e:
                logger.error("Failed to load watermark from Snowflake, falling back to local memory", extra={"source": source, "error": str(e)})

        if source in self._watermarks:
            return self._watermarks[source]
        
        # Default fallback
        fallback = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
        logger.info("No watermark found for %s. Using default fallback.", source)
        return fallback

    def update_watermark(self, source: str, watermark: datetime) -> None:
        """
        Update the watermark for a given telemetry source.
        Only updates if the new watermark is strictly greater than the current one.
        Saves to Snowflake if active; otherwise saves to local file.
        """
        # Ensure UTC aware
        if watermark.tzinfo is None:
            watermark = watermark.replace(tzinfo=timezone.utc)

        current = self.get_watermark(source)
        if source not in self._watermarks or watermark > current:
            self._watermarks[source] = watermark

            if self.client:
                try:
                    query = f"""
                    MERGE INTO {self.settings.watermarks_table} AS target
                    USING (SELECT %s AS SOURCE_NAME, %s::TIMESTAMP_TZ AS LAST_PROCESSED_TIMESTAMP) AS source
                    ON target.SOURCE_NAME = source.SOURCE_NAME
                    WHEN MATCHED THEN
                        UPDATE SET target.LAST_PROCESSED_TIMESTAMP = source.LAST_PROCESSED_TIMESTAMP
                    WHEN NOT MATCHED THEN
                        INSERT (SOURCE_NAME, LAST_PROCESSED_TIMESTAMP)
                        VALUES (source.SOURCE_NAME, source.LAST_PROCESSED_TIMESTAMP);
                    """
                    self.client.execute_query(query, (source, watermark.isoformat()))
                    logger.debug("Watermark saved to Snowflake", extra={"source": source, "new_watermark": watermark.isoformat()})
                    return
                except Exception as e:
                    logger.error("Failed to save watermark to Snowflake, saving to local file fallback", extra={"source": source, "error": str(e)})

            # File based update if no DB client is available or DB write failed
            self._save_file()
            logger.debug("Watermark updated locally", extra={"source": source, "new_watermark": watermark.isoformat()})
        else:
            logger.debug("Watermark update ignored (not newer)", extra={"source": source, "provided": watermark.isoformat(), "current": current.isoformat()})
