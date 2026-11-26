"""Unit tests for the `terminating` workshop status.

Babylon CRDs (Workshop/MultiWorkshop/SelfPacedLab) carry a
``demo.redhat.com/reporting`` finalizer. When the reporting-operator/API
backing that finalizer is unhealthy, deletion requests never complete: the
object gets a ``metadata.deletionTimestamp`` but is never actually removed
from the cluster (observed live on the ``integration`` Babylon cluster: ~90%
of Workshop CRDs stuck terminating, some for weeks).

Such objects are surfaced as an ordinary ``terminating`` status rather than
dropped at fetch time — dropping them makes a wedged finalizer invisible,
which is exactly the condition an operator needs to see. The status gets no
special treatment in filtering; the dashboard simply leaves it out of its
default chip selection. These tests pin down that the status is derived
correctly and that it filters like any other status.
"""

import pytest

from soundcheck.schemas_workshops import WorkshopDashboardItem
from soundcheck.services import babylon_client
from soundcheck.services.workshop_service import (
    _derive_multi_workshop_status,
    _is_terminating,
    build_summary,
    derive_status,
    extract_selfpacedlab_item,
    extract_workshop_item,
    fetch_multiworkshops_from_cluster,
    fetch_selfpacedlabs_from_cluster,
    fetch_workshops_from_cluster,
    matches_filters,
)

TERMINATING_TS = "2026-09-14T10:57:52Z"


def make_workshop(name: str, *, terminating: bool = False) -> dict:
    metadata = {"name": name, "namespace": "user-test", "uid": name, "labels": {}, "annotations": {}}
    if terminating:
        metadata["deletionTimestamp"] = TERMINATING_TS
    return {
        "metadata": metadata,
        "spec": {},
        "status": {"provisionCount": {"ordered": 1, "active": 1, "failed": 0}, "userCount": {}},
    }


def make_spl(name: str, *, terminating: bool = False) -> dict:
    metadata = {"name": name, "namespace": "user-test", "labels": {}, "annotations": {}}
    if terminating:
        metadata["deletionTimestamp"] = TERMINATING_TS
    return {"metadata": metadata, "spec": {}, "status": {"poolCount": {"ready": 1}}}


def make_item(name: str, status: str) -> WorkshopDashboardItem:
    """Minimal dashboard item; only `name`/`status`/`cluster` matter to filters."""
    return WorkshopDashboardItem(
        name=name,
        namespace="user-test",
        display_name=name,
        cluster="integration",
        catalog_item="",
        requester="",
        ordered_by="",
        workshop_id="",
        workshop_url="",
        catalog_url="",
        status=status,
        created_at="",
        lifespan_start="",
        lifespan_end="",
        ready_by="",
        action_start="",
        action_stop="",
        provision_ordered=0,
        provision_active=0,
        provision_failed=0,
        provision_retries=0,
        users_assigned=0,
        users_available=0,
        users_total=0,
        white_glove=False,
        demo_team_provisioned=False,
        locked=False,
        disable_auto_stop=False,
        open_registration=False,
        access_password_set=False,
    )


def no_filters(item: WorkshopDashboardItem, **overrides):
    """Call matches_filters with every filter disabled unless overridden."""
    kwargs = {
        "clusters": None,
        "statuses": None,
        "white_glove": None,
        "provision_type": None,
        "has_failures": False,
        "from_time": None,
        "to_time": None,
        "search": None,
    }
    kwargs.update(overrides)
    return matches_filters(item, **kwargs)


class TestIsTerminating:
    def test_no_deletion_timestamp_is_not_terminating(self) -> None:
        assert _is_terminating({"metadata": {"name": "a"}}) is False

    def test_deletion_timestamp_present_is_terminating(self) -> None:
        assert _is_terminating({"metadata": {"name": "a", "deletionTimestamp": TERMINATING_TS}}) is True

    def test_missing_metadata_is_not_terminating(self) -> None:
        assert _is_terminating({}) is False


class TestDeriveStatus:
    def test_terminating_overrides_otherwise_running(self) -> None:
        """A stuck-deleting object keeps reporting live provision counts and an
        open lifespan; the deletionTimestamp is the only trustworthy signal, so
        it must win over every other branch."""
        assert derive_status("", "", 1, 1, 0, False, "started", terminating=True) == "terminating"

    def test_not_terminating_derives_normally(self) -> None:
        assert derive_status("", "", 1, 1, 0, False, "started", terminating=False) == "running"

    def test_terminating_defaults_to_false(self) -> None:
        """Existing call sites that don't pass the flag keep their behaviour."""
        assert derive_status("", "", 1, 1, 0, False, "started") == "running"


class TestExtractItems:
    def test_workshop_item_gets_terminating_status(self) -> None:
        item = extract_workshop_item(make_workshop("stuck", terminating=True), "integration")
        assert item.status == "terminating"

    def test_live_workshop_item_unaffected(self) -> None:
        item = extract_workshop_item(make_workshop("live"), "integration", "started")
        assert item.status == "running"

    def test_selfpacedlab_item_gets_terminating_status(self) -> None:
        item = extract_selfpacedlab_item(make_spl("stuck", terminating=True), "integration")
        assert item.status == "terminating"

    def test_live_selfpacedlab_item_unaffected(self) -> None:
        item = extract_selfpacedlab_item(make_spl("live"), "integration")
        assert item.status == "running"


class TestDeriveMultiWorkshopStatus:
    def test_terminating_event_reports_terminating(self) -> None:
        assert _derive_multi_workshop_status("", "", [], terminating=True) == "terminating"

    def test_terminating_children_are_ignored_in_aggregate(self) -> None:
        """A child stuck mid-deletion must not drag a live event off "running" —
        the event itself is still serving its remaining healthy children."""
        children = [make_item("a", "running"), make_item("b", "terminating")]
        assert _derive_multi_workshop_status("", "", children) == "running"

    def test_all_children_terminating_is_unknown(self) -> None:
        children = [make_item("a", "terminating"), make_item("b", "terminating")]
        assert _derive_multi_workshop_status("", "", children) == "unknown"


class TestMatchesFilters:
    """`terminating` filters exactly like any other status — no special case."""

    def test_excluded_when_status_list_omits_it(self) -> None:
        assert no_filters(make_item("stuck", "terminating"), statuses=["running", "failed"]) is False

    def test_included_when_status_list_contains_it(self) -> None:
        assert no_filters(make_item("stuck", "terminating"), statuses=["terminating"]) is True

    def test_empty_status_list_means_any_status(self) -> None:
        """No status filter matches everything, terminating included — the same as
        for `stopped` or `completed`. The dashboard hides terminating only by
        leaving it out of its *default* chip selection, so clearing all filters
        deliberately reveals it along with every other status."""
        assert no_filters(make_item("stuck", "terminating")) is True

    def test_status_selection_does_not_bypass_other_filters(self) -> None:
        item = make_item("stuck", "terminating")
        assert no_filters(item, statuses=["terminating"], clusters=["other"]) is False


class TestBuildSummary:
    def test_counts_terminating_separately(self) -> None:
        items = [make_item("a", "running"), make_item("b", "terminating"), make_item("c", "terminating")]
        summary = build_summary(items)
        assert summary.terminating == 2
        assert summary.running == 1
        assert summary.total == 3


class TestFetchFromCluster:
    """Terminating objects must survive the fetch layer — the hiding happens in
    matches_filters, so dropping them here would make opt-in impossible."""

    async def test_workshops_keeps_terminating(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_list_cluster_wide(cluster, group, version, plural, label_selector="", limit=0):
            return {"items": [make_workshop("live-one"), make_workshop("stuck", terminating=True)]}

        monkeypatch.setattr(babylon_client, "k8s_list_cluster_wide", fake_list_cluster_wide)

        items, errors = await fetch_workshops_from_cluster("integration")

        assert errors == []
        assert {i.name: i.status for i in items} == {"live-one": "running", "stuck": "terminating"}

    async def test_multiworkshops_keeps_terminating(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_list_cluster_wide(cluster, group, version, plural, label_selector="", limit=0):
            return {
                "items": [
                    {"metadata": {"name": "live-mws"}, "spec": {}},
                    {"metadata": {"name": "stuck-mws", "deletionTimestamp": TERMINATING_TS}, "spec": {}},
                ]
            }

        monkeypatch.setattr(babylon_client, "k8s_list_cluster_wide", fake_list_cluster_wide)

        items, errors = await fetch_multiworkshops_from_cluster("integration")

        assert errors == []
        assert [item["metadata"]["name"] for item in items] == ["live-mws", "stuck-mws"]

    async def test_selfpacedlabs_keeps_terminating(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_list_cluster_wide(cluster, group, version, plural, label_selector="", limit=0):
            return {"items": [make_spl("live-spl"), make_spl("stuck-spl", terminating=True)]}

        monkeypatch.setattr(babylon_client, "k8s_list_cluster_wide", fake_list_cluster_wide)

        items, errors = await fetch_selfpacedlabs_from_cluster("integration")

        assert errors == []
        assert {i.name: i.status for i in items} == {"live-spl": "running", "stuck-spl": "terminating"}
