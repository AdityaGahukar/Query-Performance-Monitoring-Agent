"""
POV-4: Application configuration framework.

All settings are loaded exclusively from environment variables or a .env file.
No secrets or credentials are ever hardcoded.

Uses pydantic-settings for strict environment-variable-driven configuration,
with grouped nested models for clean separation of concerns across subsystems.

Reference: docs/architecture/project_structure.md (core/config.py)
Reference: PROJECT_CONTEXT.md (Technology Stack)
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Subsystem Settings Groups
# ---------------------------------------------------------------------------


class SnowflakeSettings(BaseSettings):
    """
    Snowflake connection and account settings.

    POV-4 requires MONITOR privilege on target warehouses to access
    INFORMATION_SCHEMA views for real-time telemetry collection.
    """

    model_config = SettingsConfigDict(env_prefix="SNOWFLAKE_", extra="ignore")

    account: str = Field(description="Snowflake account identifier (e.g. xy12345.us-east-1).")
    user: str = Field(description="Snowflake username for the service account.")
    password: str = Field(description="Snowflake service account password.")
    warehouse: str = Field(description="Default warehouse used by POV-4 for its own queries.")
    database: str = Field(description="Database where POV-4 internal tables are stored.")
    schema_name: str = Field(
        alias="SNOWFLAKE_SCHEMA",
        description="Schema where POV-4 internal tables are stored.",
    )
    role: str = Field(description="Snowflake role assumed by the service account.")

    model_config = SettingsConfigDict(
        env_prefix="SNOWFLAKE_",
        populate_by_name=True,
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )


class GeminiSettings(BaseSettings):
    """
    Google Gemini API settings.

    Used exclusively by the Performance Analysis Agent (src/agents/analyzer.py).
    """

    model_config = SettingsConfigDict(
        env_prefix="GEMINI_",
        extra="ignore",
        protected_namespaces=("settings_",),  # suppress conflict warning for model_name field
        env_file=".env",
        env_file_encoding="utf-8",
    )

    api_key: str = Field(description="Google Gemini API key.")
    model_name: str = Field(
        default="gemini-1.5-pro",
        description="Gemini model identifier to use for RCA generation.",
    )
    request_timeout_seconds: int = Field(
        default=60,
        description="Maximum seconds to wait for a Gemini API response before triggering fallback.",
        ge=10,
        le=300,
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of retry attempts on transient Gemini API errors.",
        ge=1,
        le=10,
    )


class LoggingSettings(BaseSettings):
    """
    Structured logging configuration.

    POV-4 uses structured (JSON) logging for consistency across all modules.
    """

    model_config = SettingsConfigDict(
        env_prefix="LOG_", 
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    level: str = Field(
        default="INFO",
        description="Logging level. One of: DEBUG, INFO, WARNING, ERROR, CRITICAL.",
    )
    format: str = Field(
        default="json",
        description="Log output format. 'json' for structured logging, 'text' for development.",
    )

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got '{v}'.")
        return upper

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        allowed = {"json", "text"}
        lower = v.lower()
        if lower not in allowed:
            raise ValueError(f"LOG_FORMAT must be one of {allowed}, got '{v}'.")
        return lower


class SchedulerSettings(BaseSettings):
    """
    APScheduler polling interval configuration.

    Intervals align with the approved collection strategy.
    Reference: docs/collection-strategy.md §2
    """

    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_", 
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    query_history_interval_minutes: int = Field(
        default=5,
        description="Polling interval for QUERY_HISTORY (INFORMATION_SCHEMA). Default: 5 minutes.",
        ge=1,
        le=60,
    )
    warehouse_load_interval_minutes: int = Field(
        default=15,
        description="Polling interval for WAREHOUSE_LOAD_HISTORY. Default: 15 minutes.",
        ge=1,
        le=120,
    )
    metering_interval_minutes: int = Field(
        default=60,
        description="Polling interval for METERING_HISTORY. Default: 60 minutes (hourly).",
        ge=15,
        le=1440,
    )
    query_attribution_interval_minutes: int = Field(
        default=60,
        description="Polling interval for QUERY_ATTRIBUTION_HISTORY. Default: 60 minutes (hourly).",
        ge=15,
        le=1440,
    )


class StorageSettings(BaseSettings):
    """
    Persistence layer configuration.

    POV-4 stores all findings in Snowflake internal tables — no additional
    database infrastructure is required.
    Reference: docs/implementation_roadmap.md Phase 4 (Architectural Decision).
    """

    model_config = SettingsConfigDict(
        env_prefix="STORAGE_", 
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    findings_table: str = Field(
        default="POV4_PERFORMANCE_FINDINGS",
        description="Snowflake table name for storing PerformanceFinding records.",
    )
    watermarks_table: str = Field(
        default="POV4_WATERMARKS",
        description="Snowflake table for tracking telemetry collection watermarks.",
    )
    dlq_table: str = Field(
        default="POV4_DLQ",
        description="Snowflake table acting as Dead Letter Queue for failed alert dispatches.",
    )


# ---------------------------------------------------------------------------
# Root Application Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """
    Root application settings for POV-4.

    Loads from environment variables and an optional .env file.
    Nested settings groups are instantiated automatically.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(
        default="POV-4 Query Performance Monitoring Agent",
        description="Human-readable application name.",
    )
    app_version: str = Field(
        default="0.1.0",
        description="Application version string.",
    )
    environment: str = Field(
        default="development",
        description="Deployment environment. One of: development, staging, production.",
    )

    snowflake: SnowflakeSettings = Field(default_factory=SnowflakeSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        lower = v.lower()
        if lower not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}, got '{v}'.")
        return lower


def get_settings() -> Settings:
    """
    Returns a fully validated Settings instance.

    Intended to be used as a FastAPI dependency or called once at startup.
    All validation errors surface immediately on application boot, preventing
    silent misconfiguration in production.
    """
    return Settings()
