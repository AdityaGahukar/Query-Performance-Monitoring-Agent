"""
Watermark management for incremental telemetry collection.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict

from src.core.logging import get_logger

logger = get_logger(__name__)

# Fallback watermark: collect up to 1 hour of history if no watermark exists
DEFAULT_LOOKBACK_HOURS = 1


class WatermarkManager:
    """
    Manages watermarks for telemetry sources to ensure incremental collection.

    Design Decision:
    For Phase 2, this is implemented as a simple local JSON file store.
    This fulfills the requirement for stateful watermark handling without
    introducing database dependencies prematurely. In Phase 4 (Persistence Layer),
    this will be refactored to read/write from the Snowflake STORAGE_WATERMARKS_TABLE.
    """

    def __init__(self, state_file: str = ".watermarks.json"):
        self.state_file = state_file
        self._watermarks: Dict[str, datetime] = self._load()

    def _load(self) -> Dict[str, datetime]:
        """Load watermarks from local JSON file."""
        if not os.path.exists(self.state_file):
            return {}
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
                return {k: datetime.fromisoformat(v) for k, v in data.items()}
        except Exception as e:
            logger.error("Failed to load watermarks", extra={"error": str(e)})
            return {}

    def _save(self) -> None:
        """Save watermarks to local JSON file."""
        try:
            with open(self.state_file, "w") as f:
                data = {k: v.isoformat() for k, v in self._watermarks.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save watermarks", extra={"error": str(e)})

    def get_watermark(self, source: str) -> datetime:
        """
        Retrieve the current watermark for a given telemetry source.
        If no watermark exists, returns a default fallback timestamp.
        """
        if source in self._watermarks:
            return self._watermarks[source]
        
        # Default: start from 1 hour ago
        fallback = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
        logger.info(
            "No watermark found for %s. Using default fallback.",
            source,
        )
        return fallback

    def update_watermark(self, source: str, watermark: datetime) -> None:
        """
        Update the watermark for a given telemetry source.
        Only updates if the new watermark is strictly greater than the current one.
        """
        current = self.get_watermark(source)
        # Ensure we only move watermarks forward
        if source not in self._watermarks or watermark > current:
            self._watermarks[source] = watermark
            self._save()
            logger.debug(
                "Watermark updated",
                extra={"source": source, "new_watermark": watermark.isoformat()}
            )
        else:
            logger.debug(
                "Watermark update ignored (not newer)",
                extra={"source": source, "provided": watermark.isoformat(), "current": current.isoformat()}
            )
