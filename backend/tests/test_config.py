"""Unit tests for soundcheck.config.Settings."""

import pytest

from soundcheck.config import Settings, _derive_async_db_url

# All env vars the Settings model reads. Cleared before every test so the
# real host environment / repo-root .env file can't leak into results.
_ENV_VARS = (
    "CHECK_CONCURRENCY",
    "ORCHESTRATION_CONCURRENCY",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_POOL_RECYCLE",
    "MAX_SSE_CONNECTIONS",
    "VERIFY_SSL",
    "LOG_FORMAT",
    "CORS_ORIGINS",
    "API_KEY",
    "ENABLE_DOCS",
    "REDIS_URL",
    "DEMO_TEAM_EMAILS",
    "ENVIRONMENT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "DATABASE_URL",
    "ASYNC_DATABASE_URL",
    "ASYNC_DB_URL",
)


def make_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Build a Settings instance from a clean environment (no .env file)."""
    for key in _ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


class TestDefaults:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch)
        assert s.check_concurrency == 20
        assert s.orchestration_concurrency == 10
        assert s.db_pool_size == 10
        assert s.db_max_overflow == 20
        assert s.db_pool_recycle == 3600
        assert s.max_sse_connections == 200
        assert s.verify_ssl is True
        assert s.log_format == "text"
        assert s.cors_origins == ["http://localhost:5173"]
        assert s.api_key == ""
        assert s.enable_docs is True
        assert s.redis_url == "redis://localhost:6379"
        assert s.demo_team_emails == frozenset()
        assert s.environment == "development"


class TestPositiveIntFallback:
    def test_non_numeric_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, CHECK_CONCURRENCY="banana")
        assert s.check_concurrency == 20

    def test_empty_string_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, DB_POOL_SIZE="")
        assert s.db_pool_size == 10

    def test_negative_value_clamped_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, CHECK_CONCURRENCY="-5")
        assert s.check_concurrency == 1

    def test_zero_clamped_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ORCHESTRATION_CONCURRENCY="0")
        assert s.orchestration_concurrency == 1

    def test_valid_value_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, MAX_SSE_CONNECTIONS="7")
        assert s.max_sse_connections == 7


class TestCorsOrigins:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch)
        assert s.cors_origins == ["http://localhost:5173"]

    def test_comma_split_and_strip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, CORS_ORIGINS="https://a.com, https://b.com")
        assert s.cors_origins == ["https://a.com", "https://b.com"]

    def test_wildcard_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(RuntimeError, match="CORS_ORIGINS must not contain"):
            make_settings(monkeypatch, CORS_ORIGINS="*")

    def test_wildcard_among_others_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(RuntimeError, match="CORS_ORIGINS must not contain"):
            make_settings(monkeypatch, CORS_ORIGINS="https://a.com,*")


class TestDemoTeamEmails:
    def test_default_empty_and_warns(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            s = make_settings(monkeypatch)
        assert s.demo_team_emails == frozenset()
        assert any("DEMO_TEAM_EMAILS" in r.message for r in caplog.records)

    def test_lowercased_deduped_and_blank_filtered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, DEMO_TEAM_EMAILS="Foo@Example.com, bar@example.com,, foo@example.com")
        assert s.demo_team_emails == frozenset({"foo@example.com", "bar@example.com"})

    def test_non_empty_does_not_warn(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            make_settings(monkeypatch, DEMO_TEAM_EMAILS="foo@example.com")
        assert not any("DEMO_TEAM_EMAILS" in r.message for r in caplog.records)


class TestLegacyBooleanParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("on", False),  # deliberately not treated as truthy (unlike pydantic's native bool coercion)
            ("", False),
        ],
    )
    def test_verify_ssl(self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
        s = make_settings(monkeypatch, VERIFY_SSL=raw)
        assert s.verify_ssl is expected

    def test_enable_docs_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ENABLE_DOCS="false")
        assert s.enable_docs is False


class TestLogFormatAndEnvironment:
    def test_log_format_lowercased(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, LOG_FORMAT="JSON")
        assert s.log_format == "json"

    def test_environment_lowercased(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ENVIRONMENT="PRODUCTION")
        assert s.environment == "production"


class TestDeriveAsyncDbUrl:
    def test_postgres_scheme(self) -> None:
        assert _derive_async_db_url("postgres://u:p@h:5432/d") == "postgresql+asyncpg://u:p@h:5432/d"

    def test_postgresql_scheme(self) -> None:
        assert _derive_async_db_url("postgresql://u:p@h:5432/d") == "postgresql+asyncpg://u:p@h:5432/d"

    def test_already_asyncpg_is_idempotent(self) -> None:
        url = "postgresql+asyncpg://u:p@h:5432/d"
        assert _derive_async_db_url(url) == url

    def test_unsupported_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported DB scheme"):
            _derive_async_db_url("mysql://u:p@h:3306/d")

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a valid PostgreSQL URL"):
            _derive_async_db_url(None)

    def test_missing_scheme_separator_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a valid PostgreSQL URL"):
            _derive_async_db_url("not-a-url")


class TestGetAsyncDbUrl:
    def test_explicit_async_database_url_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ASYNC_DATABASE_URL="postgresql+asyncpg://x:y@z:5432/w")
        assert s.get_async_db_url() == "postgresql+asyncpg://x:y@z:5432/w"

    def test_explicit_async_db_url_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ASYNC_DB_URL="postgresql+asyncpg://x:y@z:5432/w")
        assert s.get_async_db_url() == "postgresql+asyncpg://x:y@z:5432/w"

    def test_database_url_is_derived(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, DATABASE_URL="postgresql://x:y@z:5432/w")
        assert s.get_async_db_url() == "postgresql+asyncpg://x:y@z:5432/w"

    def test_default_derived_from_postgres_parts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(
            monkeypatch,
            POSTGRES_USER="u",
            POSTGRES_PASSWORD="p",
            POSTGRES_HOST="h",
            POSTGRES_PORT="1234",
            POSTGRES_DB="d",
        )
        assert s.get_async_db_url() == "postgresql+asyncpg://u:p@h:1234/d"

    def test_default_password_used_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch)
        assert s.get_async_db_url() == "postgresql+asyncpg://soundcheck:soundcheck_dev@localhost:5432/soundcheck"


class TestWarnDefaultCredentials:
    def test_development_with_defaults_warns_not_raises(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        s = make_settings(monkeypatch, ENVIRONMENT="development")
        with caplog.at_level("WARNING"):
            s.warn_default_credentials()
        assert any("default database credentials" in r.message for r in caplog.records)

    def test_non_development_without_password_or_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ENVIRONMENT="production")
        with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD or DATABASE_URL"):
            s.warn_default_credentials()

    def test_non_development_with_password_is_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ENVIRONMENT="production", POSTGRES_PASSWORD="secret")
        s.warn_default_credentials()  # should not raise

    def test_non_development_with_database_url_is_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ENVIRONMENT="staging", DATABASE_URL="postgresql://x:y@z/d")
        s.warn_default_credentials()  # should not raise

    def test_empty_string_password_still_counts_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = make_settings(monkeypatch, ENVIRONMENT="production", POSTGRES_PASSWORD="")
        with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD or DATABASE_URL"):
            s.warn_default_credentials()
