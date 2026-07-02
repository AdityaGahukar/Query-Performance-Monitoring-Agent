"""
Tests for POV-4 configuration framework.

Covers:
    - Default values for all optional settings
    - Environment variable loading via monkeypatch
    - Validation errors for invalid enum-like fields (LOG_LEVEL, ENVIRONMENT, LOG_FORMAT)
    - Nested settings group instantiation
    - Scheduler interval boundary validation (ge/le)
    - get_settings() factory function

All tests use environment variable monkeypatching — no real .env file or
Snowflake credentials are required.
"""

import pytest
from pydantic import ValidationError

from src.core.config import (
    GeminiSettings,
    LLMSettings,
    LoggingSettings,
    SchedulerSettings,
    Settings,
    SnowflakeSettings,
    StorageSettings,
    get_settings,
)


# ---------------------------------------------------------------------------
# Minimal valid env var sets for each subsystem
# ---------------------------------------------------------------------------

SNOWFLAKE_ENVS = {
    "SNOWFLAKE_ACCOUNT": "xy12345.us-east-1",
    "SNOWFLAKE_USER": "pov4_service",
    "SNOWFLAKE_PASSWORD": "s3cr3t",
    "SNOWFLAKE_WAREHOUSE": "POV4_WH",
    "SNOWFLAKE_DATABASE": "POV4_DB",
    "SNOWFLAKE_SCHEMA": "POV4_SCHEMA",
    "SNOWFLAKE_ROLE": "POV4_ROLE",
}

GEMINI_ENVS = {
    "GEMINI_API_KEY": "test_api_key_abc123",
}

LLM_ENVS = {
    "LLM_API_KEY": "test_nvidia_key_abc123",
}

ROOT_ENVS = {
    **SNOWFLAKE_ENVS,
    **GEMINI_ENVS,
    **LLM_ENVS,
}


# =============================================================================
# SnowflakeSettings tests
# =============================================================================


class TestSnowflakeSettings:
    def test_loads_from_env(self, monkeypatch):
        for k, v in SNOWFLAKE_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = SnowflakeSettings()
        assert settings.account == "xy12345.us-east-1"
        assert settings.user == "pov4_service"
        assert settings.warehouse == "POV4_WH"
        assert settings.schema_name == "POV4_SCHEMA"
        assert settings.role == "POV4_ROLE"

    def test_missing_account_raises(self, monkeypatch):
        for k, v in SNOWFLAKE_ENVS.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("SNOWFLAKE_ACCOUNT", raising=False)
        with pytest.raises(ValidationError, match="account"):
            SnowflakeSettings()

    def test_missing_password_raises(self, monkeypatch):
        for k, v in SNOWFLAKE_ENVS.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("SNOWFLAKE_PASSWORD", raising=False)
        with pytest.raises(ValidationError, match="password"):
            SnowflakeSettings()


# =============================================================================
# GeminiSettings tests
# =============================================================================


class TestGeminiSettings:
    def test_default_model_name(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        settings = GeminiSettings()
        assert settings.model_name == "gemini-3.5-flash"

    def test_default_timeout(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        settings = GeminiSettings()
        assert settings.request_timeout_seconds == 60

    def test_default_prompt_version(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        settings = GeminiSettings()
        assert settings.prompt_version == "v1_default"

    def test_default_max_retries(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        settings = GeminiSettings()
        assert settings.max_retries == 3

    def test_custom_model_name(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        monkeypatch.setenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")
        settings = GeminiSettings()
        assert settings.model_name == "gemini-2.0-flash"

    def test_timeout_too_low_raises(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "5")
        with pytest.raises(ValidationError, match="request_timeout_seconds"):
            GeminiSettings()

    def test_timeout_too_high_raises(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        monkeypatch.setenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "999")
        with pytest.raises(ValidationError, match="request_timeout_seconds"):
            GeminiSettings()

    def test_missing_api_key_raises(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValidationError, match="API key for Gemini"):
            Settings()


# =============================================================================
# LoggingSettings tests
# =============================================================================


class TestLoggingSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("LOG_FORMAT", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        settings = LoggingSettings()
        assert settings.level == "INFO"
        assert settings.format == "json"

    def test_valid_level_uppercased(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        settings = LoggingSettings()
        assert settings.level == "DEBUG"

    def test_invalid_level_raises(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
        with pytest.raises(ValidationError, match="LOG_LEVEL"):
            LoggingSettings()

    def test_valid_text_format(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "text")
        settings = LoggingSettings()
        assert settings.format == "text"

    def test_invalid_format_raises(self, monkeypatch):
        monkeypatch.setenv("LOG_FORMAT", "yaml")
        with pytest.raises(ValidationError, match="LOG_FORMAT"):
            LoggingSettings()


# =============================================================================
# SchedulerSettings tests
# =============================================================================


class TestSchedulerSettings:
    def test_defaults_match_collection_strategy(self):
        """
        Defaults must match docs/collection-strategy.md §2:
            QUERY_HISTORY: 5 min
            WAREHOUSE_LOAD: 15 min
            METERING: 60 min
            QUERY_ATTRIBUTION: 60 min
        """
        settings = SchedulerSettings()
        assert settings.query_history_interval_minutes == 5
        assert settings.warehouse_load_interval_minutes == 15
        assert settings.metering_interval_minutes == 60
        assert settings.query_attribution_interval_minutes == 60

    def test_query_history_interval_too_low_raises(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_QUERY_HISTORY_INTERVAL_MINUTES", "0")
        with pytest.raises(ValidationError, match="query_history_interval_minutes"):
            SchedulerSettings()

    def test_metering_interval_too_low_raises(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_METERING_INTERVAL_MINUTES", "10")
        with pytest.raises(ValidationError, match="metering_interval_minutes"):
            SchedulerSettings()


# =============================================================================
# StorageSettings tests
# =============================================================================


class TestStorageSettings:
    def test_default_table_names(self):
        settings = StorageSettings()
        assert settings.findings_table == "POV4_PERFORMANCE_FINDINGS"
        assert settings.watermarks_table == "POV4_WATERMARKS"
        assert settings.dlq_table == "POV4_DLQ"

    def test_custom_table_names(self, monkeypatch):
        monkeypatch.setenv("STORAGE_FINDINGS_TABLE", "CUSTOM_FINDINGS")
        settings = StorageSettings()
        assert settings.findings_table == "CUSTOM_FINDINGS"


# =============================================================================
# Root Settings tests
# =============================================================================


class TestSettings:
    def test_defaults(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert settings.environment == "development"
        assert settings.app_version == "0.1.0"

    def test_invalid_environment_raises(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("ENVIRONMENT", "qa")
        with pytest.raises(ValidationError, match="ENVIRONMENT"):
            Settings()

    def test_environment_case_insensitive(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("ENVIRONMENT", "PRODUCTION")
        settings = Settings()
        assert settings.environment == "production"

    def test_nested_snowflake_settings(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert isinstance(settings.snowflake, SnowflakeSettings)
        assert settings.snowflake.account == "xy12345.us-east-1"

    def test_nested_gemini_settings(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert isinstance(settings.gemini, GeminiSettings)

    def test_nested_scheduler_settings(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert isinstance(settings.scheduler, SchedulerSettings)
        assert settings.scheduler.query_history_interval_minutes == 5

    def test_nested_storage_settings(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert isinstance(settings.storage, StorageSettings)

    def test_nested_logging_settings(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert isinstance(settings.logging, LoggingSettings)

    def test_nested_llm_settings(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = Settings()
        assert isinstance(settings.llm, LLMSettings)
        assert settings.llm.provider == "nvidia"

    def test_nvidia_provider_validation(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        # Switch to nvidia
        monkeypatch.setenv("LLM_PROVIDER", "nvidia")
        
        # Missing LLM_API_KEY raises ValidationError
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        with pytest.raises(ValidationError, match="API key for NVIDIA"):
            Settings()

        # Adding LLM_API_KEY resolves correctly
        monkeypatch.setenv("LLM_API_KEY", "nvidia-key")
        settings = Settings()
        assert settings.llm.provider == "nvidia"
        assert settings.llm.api_key == "nvidia-key"
        assert settings.llm.model == "meta/llama-3.1-8b-instruct"


# =============================================================================
# get_settings factory tests
# =============================================================================


class TestGetSettings:
    def test_returns_settings_instance(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_returns_fresh_instance_each_call(self, monkeypatch):
        for k, v in ROOT_ENVS.items():
            monkeypatch.setenv(k, v)
        s1 = get_settings()
        s2 = get_settings()
        # Both should be fully valid Settings objects.
        assert s1.app_name == s2.app_name
