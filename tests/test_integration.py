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
