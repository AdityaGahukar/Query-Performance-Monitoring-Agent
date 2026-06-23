import os
import pytest
from src.services.snowflake_client import SnowflakeClient

# Skip the entire module if Snowflake credentials are not actually provided.
# We check a specific environment variable to signify we want integration tests.
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_SNOWFLAKE_INTEGRATION_TESTS"),
    reason="Snowflake integration tests disabled (set RUN_SNOWFLAKE_INTEGRATION_TESTS=1 to enable)"
)

def test_live_connection():
    """
    Attempts a real connection to Snowflake and executes a simple query.
    If credentials in Settings are invalid or missing, this will fail.
    """
    with SnowflakeClient() as client:
        result = client.fetch_one("SELECT CURRENT_VERSION() as v", None)
        assert result is not None
        assert "V" in result or "v" in result


def test_live_repository_and_watermark_manager(valid_performance_finding):
    """
    Validates live write and read operations for both SnowflakeRepository and WatermarkManager.
    """
    from src.storage.repository import SnowflakeRepository
    from src.services.watermark_manager import WatermarkManager
    from src.domain.models import PerformanceFinding, AlertEvent
    from src.domain.enums import AlertDestination, AlertStatus
    from datetime import datetime, timezone
    from uuid import uuid4
    
    with SnowflakeClient() as client:
        # 1. Initialize schema
        repo = SnowflakeRepository(client)
        repo.initialize_schema()
        
        # 2. Save and retrieve finding
        finding_kwargs = dict(valid_performance_finding)
        finding_kwargs["query_id"] = f"test-query-{uuid4()}"
        finding = PerformanceFinding(**finding_kwargs)
        repo.save_finding(finding)
        
        retrieved = repo.get_finding(finding.finding_id)
        assert retrieved is not None
        assert retrieved.query_id == finding.query_id
        assert retrieved.overall_severity == finding.overall_severity
        
        # 3. Save and retrieve alert event (DLQ)
        event = AlertEvent(
            alert_id=uuid4(),
            finding_reference=finding.finding_id,
            destination=AlertDestination.TEAMS,
            status=AlertStatus.FAILED,
        )
        repo.save_alert_event(event)
        
        retrieved_event = repo.get_alert_event(event.alert_id)
        assert retrieved_event is not None
        assert retrieved_event.status == AlertStatus.FAILED
        assert retrieved_event.destination == AlertDestination.TEAMS
        
        # 4. WatermarkManager database interaction
        wm = WatermarkManager(client=client)
        source = f"TEST_SOURCE_{uuid4()}"
        now = datetime.now(timezone.utc)
        
        # Update and save
        wm.update_watermark(source, now)
        
        # Re-fetch from a clean manager instance to verify it loads from Snowflake
        wm_new = WatermarkManager(client=client)
        loaded = wm_new.get_watermark(source)
        # Snowflake timestamps may lose some microsecond precision, so compare within 1 second
        assert abs((loaded - now).total_seconds()) < 1.0

