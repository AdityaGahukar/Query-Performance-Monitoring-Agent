import json
import os
from datetime import datetime, timedelta, timezone
from tempfile import NamedTemporaryFile

import pytest

from src.services.watermark_manager import WatermarkManager


def test_watermark_manager_fallback():
    # Use a file that doesn't exist to test fallback behavior
    wm = WatermarkManager(state_file="nonexistent.json")
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
