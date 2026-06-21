import os
from unittest.mock import MagicMock, patch

import pytest
from snowflake.connector.errors import OperationalError, ProgrammingError

from src.services.snowflake_client import SnowflakeClient


@pytest.fixture
def mock_snowflake_connect():
    with patch("snowflake.connector.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.is_closed.return_value = False
        mock_connect.return_value = mock_conn
        yield mock_connect


def test_client_connects_and_closes(mock_snowflake_connect):
    client = SnowflakeClient()
    assert client.conn is None
    
    client.connect()
    assert client.conn is not None
    assert mock_snowflake_connect.call_count == 1
    
    client.close()
    assert client.conn is None


def test_client_context_manager(mock_snowflake_connect):
    with SnowflakeClient() as client:
        assert client.conn is not None
        mock_snowflake_connect.assert_called_once()
    assert client.conn is None


def test_execute_query(mock_snowflake_connect):
    client = SnowflakeClient()
    mock_cursor = MagicMock()
    mock_snowflake_connect.return_value.cursor.return_value.__enter__.return_value = mock_cursor

    client.execute_query("SELECT 1", {"param": "val"})
    mock_cursor.execute.assert_called_once_with("SELECT 1", {"param": "val"})


def test_fetch_many(mock_snowflake_connect):
    client = SnowflakeClient()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{"col": 1}, {"col": 2}]
    mock_snowflake_connect.return_value.cursor.return_value.__enter__.return_value = mock_cursor

    results = client.fetch_many("SELECT col", None)
    assert len(results) == 2
    assert results[0]["col"] == 1


def test_fetch_one(mock_snowflake_connect):
    client = SnowflakeClient()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"col": 1}
    mock_snowflake_connect.return_value.cursor.return_value.__enter__.return_value = mock_cursor

    result = client.fetch_one("SELECT col LIMIT 1", None)
    assert result == {"col": 1}


def test_retry_on_operational_error(mock_snowflake_connect):
    client = SnowflakeClient()
    mock_cursor = MagicMock()
    
    # Fail first time, succeed second time
    mock_cursor.execute.side_effect = [
        OperationalError("Transient connection drop"),
        None
    ]
    mock_snowflake_connect.return_value.cursor.return_value.__enter__.return_value = mock_cursor

    # Since we use tenacity, it should automatically retry and succeed on the second attempt
    client.execute_query("SELECT 1", None)
    
    assert mock_cursor.execute.call_count == 2


def test_no_retry_on_programming_error(mock_snowflake_connect):
    client = SnowflakeClient()
    mock_cursor = MagicMock()
    
    # Syntax error
    mock_cursor.execute.side_effect = ProgrammingError("Syntax error in SQL")
    mock_snowflake_connect.return_value.cursor.return_value.__enter__.return_value = mock_cursor

    with pytest.raises(ProgrammingError):
        client.execute_query("INVALID SQL", None)
    
    # Should fail immediately without retrying
    assert mock_cursor.execute.call_count == 1
