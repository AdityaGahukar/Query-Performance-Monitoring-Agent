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

    def __init__(self, connection: Optional[snowflake.connector.SnowflakeConnection] = None):
        self.settings = get_settings().snowflake
        self.conn = connection
        self.is_injected_conn = connection is not None

    def connect(self) -> None:
        """Establish a connection to Snowflake."""
        if self.conn and not self.conn.is_closed():
            if self.is_injected_conn:
                try:
                    with self.conn.cursor() as cur:
                        cur.execute(f"USE DATABASE {self.settings.database}")
                        cur.execute(f"USE SCHEMA {self.settings.schema_name}")
                except Exception as e:
                    logger.warning("Failed to set connection database/schema context: %s", e)
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
        if self.is_injected_conn:
            self.conn = None
            return

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
    def _prepare_query_and_params(self, query: str, params: Optional[Any]):
        if not params:
            return query, None

        if self.is_injected_conn:
            # Case 1: Dict parameters (named bindings)
            if isinstance(params, dict):
                import re
                param_names = re.findall(r"%\(([a-zA-Z0-9_]+)\)s", query)
                if param_names:
                    new_query = re.sub(r"%\([a-zA-Z0-9_]+\)s", "?", query)
                    param_list = [params[name] for name in param_names]
                    return new_query, param_list
            # Case 2: Tuple/List parameters (positional bindings)
            elif isinstance(params, (tuple, list)):
                new_query = query.replace("%s", "?")
                return new_query, params

        return query, params

    @retry(
        retry=retry_if_exception_type(OperationalError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Execute a query without returning results (e.g., DDL, DML)."""
        self.connect()
        q, p = self._prepare_query_and_params(query, params)
        try:
            with self.conn.cursor() as cur:
                cur.execute(q, p)
                logger.debug("Query executed successfully", extra={"query": q})
        except ProgrammingError as e:
            logger.error("Snowflake syntax or programming error", extra={"query": q, "error": str(e)})
            raise
        except Exception as e:
            logger.error("Failed to execute query", extra={"query": q, "error": str(e)})
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
        q, p = self._prepare_query_and_params(query, params)
        try:
            with self.conn.cursor(snowflake.connector.DictCursor) as cur:
                cur.execute(q, p)
                results = cur.fetchall()
                logger.debug("Fetched %d rows", len(results), extra={"query": q})
                return results
        except ProgrammingError as e:
            logger.error("Snowflake syntax or programming error", extra={"query": q, "error": str(e)})
            raise
        except Exception as e:
            logger.error("Failed to fetch records", extra={"query": q, "error": str(e)})
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
        q, p = self._prepare_query_and_params(query, params)
        try:
            with self.conn.cursor(snowflake.connector.DictCursor) as cur:
                cur.execute(q, p)
                result = cur.fetchone()
                logger.debug("Fetch one completed", extra={"query": q})
                return result
        except ProgrammingError as e:
            logger.error("Snowflake syntax or programming error", extra={"query": q, "error": str(e)})
            raise
        except Exception as e:
            logger.error("Failed to fetch record", extra={"query": q, "error": str(e)})
            raise
