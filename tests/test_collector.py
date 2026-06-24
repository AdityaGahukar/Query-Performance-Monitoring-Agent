from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.domain.models import TelemetrySnapshot
from src.services.collector import TelemetryCollector


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def mock_wm():
    wm = MagicMock()
    wm.get_watermark.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return wm


def test_collect_query_history_updates_watermark(mock_client, mock_wm):
    collector = TelemetryCollector(mock_client, mock_wm)
    
    # Mock the SQL read to avoid file IO issues in some test envs
    with patch.object(collector, "_read_sql", return_value="SELECT QUERY"):
        mock_client.fetch_many.return_value = [
            {"QUERY_ID": "Q1", "START_TIME": datetime(2026, 1, 2, tzinfo=timezone.utc)},
            {"QUERY_ID": "Q2", "START_TIME": datetime(2026, 1, 3, tzinfo=timezone.utc)},
        ]
        
        results = collector.collect_query_history()
        
        assert len(results) == 2
        mock_client.fetch_many.assert_called_once()
        mock_wm.update_watermark.assert_called_once_with("QUERY_HISTORY", datetime(2026, 1, 3, tzinfo=timezone.utc))


def test_get_query_operator_stats(mock_client, mock_wm):
    collector = TelemetryCollector(mock_client, mock_wm)
    with patch.object(collector, "_read_sql", return_value="SELECT STATS"):
        mock_client.fetch_many.return_value = [{"OPERATOR_TYPE": "Aggregate"}]
        
        stats = collector.get_query_operator_stats("TEST_QID")
        
        assert len(stats) == 1
        assert stats[0]["OPERATOR_TYPE"] == "Aggregate"
        mock_client.fetch_many.assert_called_once_with("SELECT STATS", {"query_id": "TEST_QID"})


def test_collect_snapshots_alignment(mock_client, mock_wm):
    collector = TelemetryCollector(mock_client, mock_wm)
    
    # Setup the internal methods to return mock data instead of actually querying
    with patch.object(collector, "collect_query_history") as mock_qh, \
         patch.object(collector, "collect_warehouse_load_history") as mock_wh, \
         patch.object(collector, "collect_metering_history") as mock_mh, \
         patch.object(collector, "collect_query_attribution_history") as mock_attr:
        
        mock_qh.return_value = [
            {"QUERY_ID": "Q1", "WAREHOUSE_NAME": "WH1", "START_TIME": datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc)},
        ]
        mock_wh.return_value = [
            {"WAREHOUSE_NAME": "WH1", "START_TIME": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), "AVG_RUNNING": 5}
        ]
        mock_mh.return_value = [
            {"WAREHOUSE_NAME": "WH1", "START_TIME": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), "CREDITS_USED_COMPUTE": 2.5}
        ]
        mock_attr.return_value = [
            {"QUERY_ID": "Q1", "CREDITS_ATTRIBUTED_COMPUTE": 0.5}
        ]
        
        snapshots = collector.collect_snapshots()
        
        assert len(snapshots) == 1
        snap = snapshots[0]
        
        assert isinstance(snap, TelemetrySnapshot)
        assert snap.query_id == "Q1"
        assert snap.warehouse_name == "WH1"
        assert snap.warehouse_load.get("AVG_RUNNING") == 5
        assert snap.metering_context.get("CREDITS_USED_COMPUTE") == 2.5
        assert snap.query_attribution.get("CREDITS_ATTRIBUTED_COMPUTE") == 0.5
        assert snap.operator_stats is None  # Ensures lazy fetch constraint
