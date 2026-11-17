"""Unit tests for BabylonClientManager.get_default_clusters().

Builds BabylonClientManager instances directly with _initialized=True and
_cluster_configs pre-populated, so no real kubeconfig file I/O happens and
BABYLON_CLUSTERS itself never needs to be set.
"""

import pytest

from soundcheck.services.babylon_client import BabylonClientManager


def make_manager(*configured: str) -> BabylonClientManager:
    """Build a manager that looks already-initialized with the given clusters."""
    mgr = BabylonClientManager()
    mgr._initialized = True
    mgr._cluster_configs = dict.fromkeys(configured, {})
    return mgr


class TestGetDefaultClustersUnset:
    def test_env_unset_returns_all_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Backward compatibility: a deployment that never sets
        BABYLON_DEFAULT_CLUSTERS keeps today's "all clusters on by
        default" behavior."""
        monkeypatch.delenv("BABYLON_DEFAULT_CLUSTERS", raising=False)
        mgr = make_manager("east", "west")
        assert mgr.get_default_clusters() == ["east", "west"]

    def test_env_blank_string_returns_all_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", "   ")
        mgr = make_manager("east", "west")
        assert mgr.get_default_clusters() == ["east", "west"]

    def test_no_configured_clusters_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("BABYLON_DEFAULT_CLUSTERS", raising=False)
        mgr = make_manager()
        assert mgr.get_default_clusters() == []


class TestGetDefaultClustersSubset:
    def test_explicit_subset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["east","west"]')
        mgr = make_manager("east", "west", "integration")
        assert mgr.get_default_clusters() == ["east", "west"]

    def test_order_follows_configured_list_not_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Order follows get_configured_clusters(), not the env var's order."""
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["west","east"]')
        mgr = make_manager("east", "west", "integration")
        assert mgr.get_default_clusters() == ["east", "west"]

    def test_case_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["East","WEST"]')
        mgr = make_manager("east", "west", "integration")
        assert mgr.get_default_clusters() == ["east", "west"]

    def test_blank_entries_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["east","","west"]')
        mgr = make_manager("east", "west", "integration")
        assert mgr.get_default_clusters() == ["east", "west"]

    def test_single_cluster(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["east"]')
        mgr = make_manager("east", "west")
        assert mgr.get_default_clusters() == ["east"]


class TestGetDefaultClustersUnknownNames:
    def test_unknown_name_dropped_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["east","bogus"]')
        mgr = make_manager("east", "west")
        with caplog.at_level("WARNING"):
            result = mgr.get_default_clusters()
        assert result == ["east"]
        assert any("bogus" in r.message for r in caplog.records)

    def test_all_names_unknown_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["bogus","fake"]')
        mgr = make_manager("east", "west")
        assert mgr.get_default_clusters() == []


class TestGetDefaultClustersInvalidJson:
    def test_malformed_json_falls_back_to_all_configured(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["east",')
        mgr = make_manager("east", "west")
        with caplog.at_level("ERROR"):
            result = mgr.get_default_clusters()
        assert result == ["east", "west"]
        assert any("BABYLON_DEFAULT_CLUSTERS" in r.message for r in caplog.records)

    def test_json_object_instead_of_array_falls_back_to_all_configured(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '{"east": true}')
        mgr = make_manager("east", "west")
        with caplog.at_level("ERROR"):
            result = mgr.get_default_clusters()
        assert result == ["east", "west"]
        assert any("BABYLON_DEFAULT_CLUSTERS" in r.message for r in caplog.records)

    def test_non_string_entries_are_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BABYLON_DEFAULT_CLUSTERS", '["east", 1, null]')
        mgr = make_manager("east", "west")
        assert mgr.get_default_clusters() == ["east"]
