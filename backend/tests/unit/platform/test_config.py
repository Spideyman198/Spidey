"""Settings contract: env-only, fail-fast, no unsafe values."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from spidey.platform.config import Environment, Settings
from tests.conftest import make_settings


class TestSettingsValidation:
    def test_loads_from_test_environment(self) -> None:
        settings = make_settings()
        assert settings.environment is Environment.TEST
        assert settings.database_dsn.startswith("postgresql+asyncpg://")

    def test_missing_required_variables_fail_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("SPIDEY_DATABASE_URL", "SPIDEY_REDIS_URL", "SPIDEY_QDRANT_URL"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    def test_invalid_database_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_settings(database_url="mysql://user:pw@host/db")


class TestCorsOrigins:
    def test_csv_string_is_split(self) -> None:
        settings = make_settings(cors_origins="http://localhost:5173, https://app.example.com")
        assert settings.cors_origins == ["http://localhost:5173", "https://app.example.com"]

    def test_wildcard_rejected(self) -> None:
        with pytest.raises(ValidationError, match="wildcard"):
            make_settings(cors_origins="*")

    def test_non_http_origin_rejected(self) -> None:
        with pytest.raises(ValidationError, match="absolute"):
            make_settings(cors_origins="app.example.com")

    def test_empty_string_means_no_origins(self) -> None:
        assert make_settings(cors_origins="").cors_origins == []


class TestOptionalEndpoints:
    def test_empty_otel_endpoint_becomes_none(self) -> None:
        assert make_settings(otel_exporter_otlp_endpoint="").otel_exporter_otlp_endpoint is None

    def test_qdrant_endpoint_has_no_trailing_slash(self) -> None:
        settings = make_settings(qdrant_url="http://qdrant:6333/")
        assert settings.qdrant_endpoint == "http://qdrant:6333"
