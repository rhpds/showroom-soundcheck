"""Unit tests for content-hash idempotency on group creation (POST /api/groups).

Covers compute_content_hash, refresh_content_hash, find_group_by_content_hash,
get_or_create_group in session_service, and the force_create branch in
routes/groups.py.

Uses a hand-rolled fake AsyncSession rather than a live Postgres: these tests
pin the decision logic (when to reuse, when to create), which is independent
of the database. pg_advisory_xact_lock serializing concurrent callers is the
one piece that genuinely needs Postgres; it is asserted here only to the
extent that the code issues the lock before reading, and its real behaviour
belongs in an integration test.
"""

from soundcheck.models import SessionGroup
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

    `matches` are the groups a content_hash SELECT should find, oldest first
    (mirrors the real query's ORDER BY created_at ASC). The advisory-lock
    statement returns nothing and is recorded separately so tests can assert
    the lock is taken before the read.
    """

    def __init__(self, matches: list[SessionGroup] | None = None) -> None:
        self.matches = matches or []
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.added: list[SessionGroup] = []
        self.committed = False

    async def execute(self, statement, params=None):
        text = str(statement)
        self.statements.append(text)
        self.params.append(params or {})
        if "pg_advisory_xact_lock" in text:
            return FakeResult([])
        return FakeResult(list(self.matches))

    def add(self, obj: SessionGroup) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: SessionGroup) -> None:
        if obj.id is None:
            obj.id = 1


def make_group(**overrides) -> SessionGroup:
    defaults = dict(
        id=1,
        group_id="existing-group-id",
        name="Summit Day 1",
        content_hash="irrelevant-in-fixture",
        babylon_cluster="",
        source_guids=["abc12"],
        source_workshop_guids=[],
        source_resource_pools=[],
        status="pending",
    )
    return SessionGroup(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_deterministic_for_identical_input(self) -> None:
        kwargs = dict(name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster="")
        assert session_service.compute_content_hash(**kwargs) == session_service.compute_content_hash(**kwargs)

    def test_source_order_does_not_matter(self) -> None:
        """A caller re-submitting the same GUIDs in a different order must
        match -- list order in a request body is not meaningful."""
        a = session_service.compute_content_hash(
            name="Summit", guids=["abc12", "def34"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        b = session_service.compute_content_hash(
            name="Summit", guids=["def34", "abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert a == b

    def test_whitespace_does_not_matter(self) -> None:
        a = session_service.compute_content_hash(
            name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        b = session_service.compute_content_hash(
            name="  Summit  ", guids=[" abc12 "], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert a == b

    def test_blank_source_entries_are_ignored(self) -> None:
        a = session_service.compute_content_hash(
            name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        b = session_service.compute_content_hash(
            name="Summit", guids=["abc12", "", "  "], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert a == b

    def test_different_name_changes_hash(self) -> None:
        a = session_service.compute_content_hash(
            name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        b = session_service.compute_content_hash(
            name="Different", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert a != b

    def test_different_babylon_cluster_changes_hash(self) -> None:
        a = session_service.compute_content_hash(
            name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster="cluster-a"
        )
        b = session_service.compute_content_hash(
            name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster="cluster-b"
        )
        assert a != b

    def test_different_guids_changes_hash(self) -> None:
        a = session_service.compute_content_hash(
            name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        b = session_service.compute_content_hash(
            name="Summit", guids=["zzz99"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert a != b

    def test_guids_are_case_sensitive(self) -> None:
        """Unlike name/cluster, GUIDs are not lowercased -- they are opaque
        identifiers from Babylon, and silently folding case could merge
        two genuinely distinct resource claims."""
        a = session_service.compute_content_hash(
            name="Summit", guids=["ABC12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        b = session_service.compute_content_hash(
            name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert a != b

    def test_moving_a_guid_between_source_kinds_changes_hash(self) -> None:
        """guids vs workshop_guids vs resource_pools are hashed as separate
        fields, so a value appearing under a different source kind must not
        be treated as the same submission."""
        a = session_service.compute_content_hash(
            name="Summit", guids=["x1"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        b = session_service.compute_content_hash(
            name="Summit", guids=[], workshop_guids=["x1"], resource_pools=[], babylon_cluster=""
        )
        assert a != b


class TestRefreshContentHash:
    def test_matches_a_freshly_computed_hash_for_the_same_fields(self) -> None:
        grp = make_group(name="Summit", source_guids=["abc12"], babylon_cluster="")
        session_service.refresh_content_hash(grp)

        expected = session_service.compute_content_hash(
            name="Summit", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert grp.content_hash == expected

    def test_changes_when_name_changes(self) -> None:
        """This is what rename_group relies on: after `grp.name = ...`,
        refresh_content_hash must produce a new hash reflecting it."""
        grp = make_group(name="Original")
        session_service.refresh_content_hash(grp)
        before = grp.content_hash

        grp.name = "Renamed"
        session_service.refresh_content_hash(grp)

        assert grp.content_hash != before


# ---------------------------------------------------------------------------
# find_group_by_content_hash
# ---------------------------------------------------------------------------


class TestFindGroupByContentHash:
    async def test_returns_none_when_no_match(self) -> None:
        db = FakeSession(matches=[])
        assert await session_service.find_group_by_content_hash(db, "deadbeef") is None

    async def test_returns_the_oldest_match(self) -> None:
        """content_hash is not unique. Oldest-first so repeated identical
        POSTs converge on one group rather than drifting between duplicates."""
        older = make_group(id=1, group_id="older")
        newer = make_group(id=2, group_id="newer")
        # The real query ORDER BY created_at ASC; the fake just returns rows
        # in the order the test supplies, so order them oldest-first here.
        db = FakeSession(matches=[older, newer])

        found = await session_service.find_group_by_content_hash(db, "deadbeef")

        assert found is older


# ---------------------------------------------------------------------------
# get_or_create_group
# ---------------------------------------------------------------------------


class TestGetOrCreateGroup:
    async def test_returns_existing_group_without_creating(self) -> None:
        existing = make_group()
        db = FakeSession(matches=[existing])

        grp, created = await session_service.get_or_create_group(
            db,
            name="Summit Day 1",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        assert grp is existing
        assert created is False
        assert db.added == []
        assert db.committed is False

    async def test_creates_group_when_no_match(self) -> None:
        db = FakeSession(matches=[])

        grp, created = await session_service.get_or_create_group(
            db,
            name="Summit Day 1",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        assert created is True
        assert grp.name == "Summit Day 1"
        assert db.added == [grp]
        assert db.committed is True

    async def test_created_group_carries_the_matching_hash(self) -> None:
        db = FakeSession(matches=[])

        grp, _ = await session_service.get_or_create_group(
            db,
            name="Summit Day 1",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        expected = session_service.compute_content_hash(
            name="Summit Day 1", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert grp.content_hash == expected

    async def test_takes_advisory_lock_before_reading(self) -> None:
        """Ordering matters: reading first would leave a window where two
        callers both miss and both insert. The lock must come first so
        concurrent identical requests serialize."""
        db = FakeSession(matches=[])

        await session_service.get_or_create_group(
            db,
            name="Summit Day 1",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        assert "pg_advisory_xact_lock" in db.statements[0]
        assert len(db.statements) >= 2

    async def test_lock_key_is_the_content_hash(self) -> None:
        """The lock and the lookup must use the same key, or the lock
        guards nothing."""
        db = FakeSession(matches=[])

        await session_service.get_or_create_group(
            db,
            name="Summit Day 1",
            guids=["abc12"],
            workshop_guids=[],
            resource_pools=[],
        )

        expected_hash = session_service.compute_content_hash(
            name="Summit Day 1", guids=["abc12"], workshop_guids=[], resource_pools=[], babylon_cluster=""
        )
        assert "pg_advisory_xact_lock" in db.statements[0]
        assert db.params[0].get("key") == expected_hash


# ---------------------------------------------------------------------------
# Schema: force_create
# ---------------------------------------------------------------------------


class TestGroupCreateForceCreate:
    def test_defaults_to_false(self) -> None:
        assert GroupCreate(name="g", guids=["abc12"]).force_create is False

    def test_accepts_true(self) -> None:
        assert GroupCreate(name="g", guids=["abc12"], force_create=True).force_create is True

    def test_no_stable_name_field_remains(self) -> None:
        """stable_name was removed in favour of content-hash matching plus
        force_create; it must not resurface as an accepted field."""
        assert "stable_name" not in GroupCreate.model_fields
