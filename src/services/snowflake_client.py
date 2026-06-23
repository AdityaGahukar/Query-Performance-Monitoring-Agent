"""
Snowflake client integration with retry logic and connection management.
"""
import logging
from typing import Any, Dict, List, Optional

import snowflake.connector
from snowflake.connector.errors import OperationalError, ProgrammingError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)


class SnowflakeClient:
    """
    A reusable Snowflake client that manages connection lifecycle
    and executes queries with retry logic.
    """

    def __init__(self):
        self.settings = get_settings().snowflake
        self.conn: Optional[snowflake.connector.SnowflakeConnection] = None

    def connect(self) -> None:
        """Establish a connection to Snowflake."""
        if self.conn and not self.conn.is_closed():
            return

        logger.debug("Connecting to Snowflake account: %s", self.settings.account)
        self.conn = snowflake.connector.connect(
            user=self.settings.user,
            password=self.settings.password,
            account=self.settings.account,
            warehouse=self.settings.warehouse,
            database=self.settings.database,
            schema=self.settings.schema_name,
            role=self.settings.role,
        )

    def close(self) -> None:
        """Close the Snowflake connection."""
        if self.conn and not self.conn.is_closed():
            self.conn.close()
            self.conn = None
            logger.debug("Snowflake connection closed.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @retry(
        retry=retry_if_exception_type(OperationalError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Execute a query without returning results (e.g., DDL, DML)."""
        self.connect()
        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                logger.debug("Query executed successfully", extra={"query": query})
        except ProgrammingError as e:
            logger.error("Snowflake syntax or programming error", extra={"query": query, "error": str(e)})
            raise
        except Exception as e:
            logger.error("Failed to execute query", extra={"query": query, "error": str(e)})
            raise

    @retry(
        retry=retry_if_exception_type(OperationalError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def fetch_many(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Fetch multiple rows, returned as a list of dictionaries."""
        self.connect()
        try:
            with self.conn.cursor(snowflake.connector.DictCursor) as cur:
                cur.execute(query, params)
                results = cur.fetchall()
                logger.debug("Fetched %d rows", len(results), extra={"query": query})
                return results
        except ProgrammingError as e:
            logger.error("Snowflake syntax or programming error", extra={"query": query, "error": str(e)})
            raise
        except Exception as e:
            logger.error("Failed to fetch records", extra={"query": query, "error": str(e)})
            raise

    @retry(
        retry=retry_if_exception_type(OperationalError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def fetch_one(self, query: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single row as a dictionary."""
        self.connect()
        try:
            with self.conn.cursor(snowflake.connector.DictCursor) as cur:
                cur.execute(query, params)
                result = cur.fetchone()
                logger.debug("Fetch one completed", extra={"query": query})
                return result
        except ProgrammingError as e:
            logger.error("Snowflake syntax or programming error", extra={"query": query, "error": str(e)})
            raise
        except Exception as e:
            logger.error("Failed to fetch record", extra={"query": query, "error": str(e)})
            raise
