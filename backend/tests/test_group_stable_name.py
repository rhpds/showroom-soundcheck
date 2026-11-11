"""Unit tests for the stable_name idempotency key on group creation.

Covers the service-level get-or-create in session_service and the
source-mismatch guard in routes/groups.py.

Uses a hand-rolled fake AsyncSession rather than a live Postgres: these tests
pin the decision logic (when to reuse, when to create, when to reject), which
is independent of the database. The two things that genuinely need Postgres --
the UNIQUE constraint on stable_name and pg_advisory_xact_lock serializing
concurrent callers -- are asserted here only to the extent that the code issues
the lock before reading; their real behaviour belongs in an integration test.
"""

import pytest
from fastapi import HTTPException

from soundcheck.models import SessionGroup
from soundcheck.routes.groups import _reject_source_mismatch
from soundcheck.schemas import GroupCreate
from soundcheck.services import session_service


class FakeResult:
    """Stands in for the object SQLAlchemy's execute() returns."""

    def __init__(self, rows: list[SessionGroup]) -> None:
        self._rows = rows

    def scalars(self) -> "FakeResult":
        return self

    def first(self) -> SessionGroup | None:
        return self._rows[0] if self._rows else None


class FakeSession:
    """Minimal AsyncSession stand-in recording what the service did.

    `existing` is the group a SELECT should find; the advisory-lock statement
    returns nothing and is recorded separately so tests can assert the lock is
    taken before the read.
    """

    def __init__(self, existing: SessionGroup | None = None) -> None:
        self.existing = existing
        self.statements: list[str] = []
        self.added: list[SessionGroup] = []
        self.committed = False

    async def execute(self, statement, params=None):
        text = str(statement)
        self.statements.append(text)
        if "pg_advisory_xact_lock" in text:
            return FakeResult([])
        return FakeResult([self.existing] if self.existing else [])

    def add(self, obj: SessionGroup) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: SessionGroup) -> None:
        # Real refresh populates the DB-assigned PK; mimic that so callers
        # serializing the result see a populated id.
        if obj.id is None:
            obj.id = 1


def make_group(**overrides) -> SessionGroup:
    defaults = dict(
        id=1,
        group_id="existing-group-id",
        name="Existing Group",
        stable_name="summit-2026",
        babylon_cluster="",
        source_guids=["abc12"],
        source_workshop_guids=[],
        source_resource_pools=[],
        status="pending",
    )
    return SessionGroup(**{**defaults, **overrides})


def make_body(**overrides) -> GroupCreate:
    defaults = dict(
        name="Existing Group",
        stable_name="summit-2026",
        guids=["abc12"],
        workshop_guids=[],
        resource_pools=[],
        babylon_cluster="",
    )
    return GroupCreate(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# get_or_create_group_by_stable_name
# ---------------------------------------------------------------------------


class TestGetOrCreateGroupByStableName:
    async def test_returns_existing_group_without_creating(self) -> None:
        """The whole point of the key: a repeat POST must not make a duplicate."""
        existing = make_group()
        db = FakeSession(existing=existing)

        grp, created = await session_service.get_or_create_group_by_stable_name(
            db,
            stable_name="summit-2026",
            name="Different Display Name",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        assert grp is existing
        assert created is False
        assert db.added == []
        assert db.committed is False

    async def test_creates_group_when_stable_name_is_unseen(self) -> None:
        db = FakeSession(existing=None)

        grp, created = await session_service.get_or_create_group_by_stable_name(
            db,
            stable_name="summit-2026",
            name="Summit Day 1",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        assert created is True
        assert grp.stable_name == "summit-2026"
        assert grp.name == "Summit Day 1"
        assert db.added == [grp]
        assert db.committed is True

    async def test_takes_advisory_lock_before_reading(self) -> None:
        """Ordering matters: reading first would leave a window where two
        callers both miss and both insert. The lock must come first so
        concurrent callers for the same key serialize."""
        db = FakeSession(existing=None)

        await session_service.get_or_create_group_by_stable_name(
            db,
            stable_name="summit-2026",
            name="Summit Day 1",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        assert "pg_advisory_xact_lock" in db.statements[0]
        assert len(db.statements) >= 2

    async def test_lock_key_is_the_trimmed_stable_name(self) -> None:
        """Lock and lookup must use the same key, or the lock guards nothing."""
        db = FakeSession(existing=None)

        await session_service.get_or_create_group_by_stable_name(
            db,
            stable_name="  summit-2026  ",
            name="Summit Day 1",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        assert db.added[0].stable_name == "summit-2026"


class TestFindGroupByStableName:
    async def test_returns_none_for_blank_key(self) -> None:
        """A blank key must never match. Stored stable_name is NULL when unused,
        so a blank lookup that reached the DB could only ever match nothing --
        but short-circuiting keeps a '' key from being treated as meaningful."""
        db = FakeSession(existing=make_group())

        assert await session_service.find_group_by_stable_name(db, "   ") is None
        assert db.statements == []

    async def test_trims_before_lookup(self) -> None:
        db = FakeSession(existing=make_group())

        found = await session_service.find_group_by_stable_name(db, "  summit-2026  ")

        assert found is not None


class TestCreateGroupStableNameNormalisation:
    async def test_empty_stable_name_is_stored_as_null(self) -> None:
        """NULL, not '': the column is UNIQUE, and Postgres allows many NULLs
        but only one ''. Storing '' would make the second group created without
        a stable_name violate the constraint."""
        db = FakeSession()

        grp = await session_service.create_group(
            db,
            name="No Key",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
            stable_name="",
        )

        assert grp.stable_name is None

    async def test_omitted_stable_name_is_null(self) -> None:
        db = FakeSession()

        grp = await session_service.create_group(
            db,
            name="No Key",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        assert grp.stable_name is None


# ---------------------------------------------------------------------------
# _reject_source_mismatch
# ---------------------------------------------------------------------------


class TestRejectSourceMismatch:
    def test_identical_sources_pass(self) -> None:
        _reject_source_mismatch(make_body(), make_group(), "")

    def test_source_order_is_not_a_mismatch(self) -> None:
        """Sources are compared as sets. Requiring callers to preserve list
        order would make an otherwise identical retry fail arbitrarily."""
        grp = make_group(source_guids=["abc12", "def34"])
        body = make_body(guids=["def34", "abc12"])

        _reject_source_mismatch(body, grp, "")

    def test_different_guids_rejected(self) -> None:
        """Reuse returns the stored group untouched, so accepting a differing
        body would hand back a group lacking the GUIDs the caller just sent."""
        grp = make_group(source_guids=["abc12"])
        body = make_body(guids=["zzz99"])

        with pytest.raises(HTTPException) as exc:
            _reject_source_mismatch(body, grp, "")

        assert exc.value.status_code == 409
        assert "guids" in exc.value.detail

    def test_added_guid_rejected(self) -> None:
        grp = make_group(source_guids=["abc12"])
        body = make_body(guids=["abc12", "def34"])

        with pytest.raises(HTTPException) as exc:
            _reject_source_mismatch(body, grp, "")

        assert exc.value.status_code == 409

    def test_different_workshop_guids_rejected(self) -> None:
        grp = make_group(source_workshop_guids=["ws-1"])
        body = make_body(workshop_guids=["ws-2"])

        with pytest.raises(HTTPException) as exc:
            _reject_source_mismatch(body, grp, "")

        assert "workshop_guids" in exc.value.detail

    def test_different_resource_pools_rejected(self) -> None:
        grp = make_group(source_resource_pools=["pool-a"])
        body = make_body(resource_pools=["pool-b"])

        with pytest.raises(HTTPException) as exc:
            _reject_source_mismatch(body, grp, "")

        assert "resource_pools" in exc.value.detail

    def test_different_cluster_rejected(self) -> None:
        grp = make_group(babylon_cluster="cluster-a")
        body = make_body()

        with pytest.raises(HTTPException) as exc:
            _reject_source_mismatch(body, grp, "cluster-b")

        assert "babylon_cluster" in exc.value.detail

    def test_display_name_difference_is_not_a_mismatch(self) -> None:
        """Only sources are compared. `name` is a mutable display label and is
        renameable after the fact, so differing on it must not 409."""
        grp = make_group(name="Original Name")
        body = make_body(name="Renamed In Request")

        _reject_source_mismatch(body, grp, "")

    def test_all_mismatched_fields_are_named(self) -> None:
        """The error has to be actionable, so it lists every differing field."""
        grp = make_group(source_guids=["abc12"], source_resource_pools=["pool-a"])
        body = make_body(guids=["zzz99"], resource_pools=["pool-b"])

        with pytest.raises(HTTPException) as exc:
            _reject_source_mismatch(body, grp, "")

        assert "guids" in exc.value.detail
        assert "resource_pools" in exc.value.detail


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestGroupCreateStableNameValidation:
    def test_defaults_to_none(self) -> None:
        assert GroupCreate(name="g", guids=["abc12"]).stable_name is None

    def test_accepts_identifier_charset(self) -> None:
        assert GroupCreate(name="g", stable_name="summit-2026_v1.2", guids=["abc12"]).stable_name == "summit-2026_v1.2"

    @pytest.mark.parametrize("bad", ["has space", "has/slash", "has:colon", "wild*card"])
    def test_rejects_non_identifier_characters(self, bad: str) -> None:
        """stable_name reuses IdentifierStr: it is an API key echoed back in
        errors and used as an advisory-lock input, so the charset stays tight."""
        with pytest.raises(ValueError):
            GroupCreate(name="g", stable_name=bad, guids=["abc12"])

    def test_rejects_overlong_value(self) -> None:
        with pytest.raises(ValueError):
            GroupCreate(name="g", stable_name="a" * 256, guids=["abc12"])
