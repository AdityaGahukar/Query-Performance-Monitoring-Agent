import json
import os
from datetime import datetime, timedelta, timezone
from tempfile import NamedTemporaryFile

from unittest.mock import MagicMock
import pytest

from src.services.watermark_manager import WatermarkManager


def test_watermark_manager_fallback():
    # Use a file that doesn't exist to test fallback behavior
    import uuid
    state_file = f"nonexistent_{uuid.uuid4()}.json"
    wm = WatermarkManager(state_file=state_file)
    watermark = wm.get_watermark("TEST_SOURCE")
    
    # The default fallback is roughly 1 hour ago
    now = datetime.now(timezone.utc)
    diff = now - watermark
    # Allow some buffer for execution time
    assert timedelta(minutes=59) < diff < timedelta(minutes=61)


def test_watermark_manager_save_and_load():
    with NamedTemporaryFile(delete=False) as f:
        state_file = f.name
        
    try:
        wm = WatermarkManager(state_file=state_file)
        
        test_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        wm.update_watermark("MY_SOURCE", test_time)
        
        # Verify it updated in memory
        assert wm.get_watermark("MY_SOURCE") == test_time
        
        # Instantiate a new manager to verify it loads from file
        wm_new = WatermarkManager(state_file=state_file)
        assert wm_new.get_watermark("MY_SOURCE") == test_time
        
    finally:
        os.remove(state_file)


def test_watermark_manager_only_moves_forward():
    with NamedTemporaryFile(delete=False) as f:
        state_file = f.name

    try:
        wm = WatermarkManager(state_file=state_file)
        
        time1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        time2 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc) # Older!
        
        wm.update_watermark("SOURCE", time1)
        assert wm.get_watermark("SOURCE") == time1
        
        # Attempt to set it backwards
        wm.update_watermark("SOURCE", time2)
        
        # It should ignore the older watermark
        assert wm.get_watermark("SOURCE") == time1

    finally:
        os.remove(state_file)


def test_watermark_manager_database_load():
    mock_client = MagicMock()
    test_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_client.fetch_one.return_value = {"LAST_PROCESSED_TIMESTAMP": test_time}

    wm = WatermarkManager(client=mock_client)
    watermark = wm.get_watermark("TEST_SOURCE")

    # Verify it queries the DB
    mock_client.fetch_one.assert_called_once()
    assert watermark == test_time


def test_watermark_manager_database_save():
    mock_client = MagicMock()
    mock_client.fetch_one.return_value = None  # Force fallback lookup first

    wm = WatermarkManager(client=mock_client)
    test_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    wm.update_watermark("TEST_SOURCE", test_time)

    # Verify it merges/writes to the DB
    mock_client.execute_query.assert_called_once()
    args, _ = mock_client.execute_query.call_args
    assert "MERGE INTO" in args[0]
    assert "TEST_SOURCE" in args[1]
    assert test_time.isoformat() in args[1]


def test_watermark_manager_save_file_error():
    wm = WatermarkManager(state_file="dummy.json")
    from unittest.mock import patch
    with patch("builtins.open", side_effect=PermissionError("no write access")):
        # This should catch the exception and log it, but not raise it
        wm.update_watermark("TEST_SOURCE", datetime.now(timezone.utc))


def test_watermark_manager_database_load_naive_timestamp():
    mock_client = MagicMock()
    naive_time = datetime(2026, 1, 1, 12, 0, 0)
    mock_client.fetch_one.return_value = {"LAST_PROCESSED_TIMESTAMP": naive_time}

    wm = WatermarkManager(client=mock_client)
    watermark = wm.get_watermark("TEST_SOURCE")
    assert watermark.tzinfo == timezone.utc


def test_watermark_manager_database_load_error_fallback():
    mock_client = MagicMock()
    mock_client.fetch_one.side_effect = Exception("DB error")
    
    import uuid
    state_file = f"nonexistent_{uuid.uuid4()}.json"
    wm = WatermarkManager(client=mock_client, state_file=state_file)
    watermark = wm.get_watermark("TEST_SOURCE")
    # It should catch the error and return fallback
    assert isinstance(watermark, datetime)


def test_watermark_manager_update_naive_timestamp():
    import uuid
    state_file = f"nonexistent_{uuid.uuid4()}.json"
    wm = WatermarkManager(state_file=state_file)
    naive_time = datetime(2026, 1, 1, 12, 0, 0)
    wm.update_watermark("TEST_SOURCE", naive_time)
    assert wm.get_watermark("TEST_SOURCE").tzinfo == timezone.utc


def test_watermark_manager_database_save_error_fallback():
    mock_client = MagicMock()
    mock_client.fetch_one.return_value = None
    mock_client.execute_query.side_effect = Exception("DB error")
    
    with NamedTemporaryFile(delete=False) as f:
        state_file = f.name
        
    try:
        wm = WatermarkManager(client=mock_client, state_file=state_file)
        test_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        wm.update_watermark("TEST_SOURCE", test_time)
        
        # It should have caught the exception and saved to the local file instead
        wm_new = WatermarkManager(state_file=state_file)
        assert wm_new.get_watermark("TEST_SOURCE") == test_time
    finally:
        os.remove(state_file)


def test_watermark_manager_load_corrupt_file():
    with NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("{invalid json")
        state_file = f.name
        
    try:
        wm = WatermarkManager(state_file=state_file)
        # Should catch error and return empty watermarks dict
        assert wm._watermarks == {}
    finally:
        os.remove(state_file)


