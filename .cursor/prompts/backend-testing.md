# Backend Testing Agent Prompt

You are an expert Python test engineer specializing in **FastAPI**, **pytest-asyncio**, **SQLModel/SQLAlchemy async**, **SAQ task queues**, **Redis**, and **production-grade test architecture**. Your task is to create and verify a comprehensive test suite for the Showroom Soundcheck backend located at `backend/soundcheck/`.

## Codebase Overview

This is a fully async Python 3.12+ FastAPI application that performs health checks against "showroom" lab environments. It deploys to both OpenShift and VMs.

### Tech Stack

| Category | Technology |
|----------|------------|
| Language | Python >= 3.12 |
| Web framework | FastAPI + Uvicorn (ASGI) |
| ORM / models | SQLModel (Pydantic v2 + SQLAlchemy 2.x async) |
| DB driver | asyncpg (via `sqlalchemy[asyncio]`) |
| Database | PostgreSQL 16 |
| Migrations | Alembic (async) |
| Task queue | SAQ (`saq[redis,web,hiredis]`) — two queues: `orchestration` + `checks` |
| Cache / pub-sub | Redis (hiredis accelerated) |
| HTTP client | httpx (async) — health probes + Kubernetes API |
| Config | Environment variables parsed in `config.py` |
| Linting | Ruff |

### Architecture

```
soundcheck/
├── main.py              # FastAPI app, lifespan, CORS, router includes
├── config.py            # Env-var config: DB URLs, REDIS_URL, concurrency settings
├── database.py          # Async engine, session factory, DbSession dependency
├── models.py            # SQLModel table models (CheckSession, SessionTarget, CheckResult, SessionGroup, GroupRun)
├── schemas.py           # Pydantic v2 request/response schemas
├── utils.py             # GUID extraction, URL allowlist (SSRF), input validation, display labels
├── worker.py            # SAQ queue definitions, lifecycle hooks, settings dicts
├── routes/
│   ├── health.py        # GET /ping, /health, /config/clusters
│   ├── check.py         # GET /check (deep-link session creation)
│   ├── sessions.py      # Session CRUD, clone, run, pin, SSE streaming
│   ├── groups.py        # Group CRUD, members, run, sync-metadata, SSE streaming
│   └── _serializers.py  # Shared response serialization helpers
├── services/
│   ├── check_service.py  # HTTP health check engine (single-target checks, no DB)
│   ├── session_service.py # Session/group DB orchestration, finalization
│   ├── babylon_service.py # K8s GUID/Workshop/ResourcePool resolution
│   └── babylon_client.py  # httpx-based K8s API client manager
└── tasks/
    ├── __init__.py      # TaskContext TypedDict for typed SAQ worker ctx
    ├── orchestration.py # Coordinator tasks: run_session_checks, run_group, run_single_source, sync_metadata, sweep_stale_sessions
    ├── checks.py        # Leaf task: check_target (individual HTTP health checks)
    └── events.py        # Redis Pub/Sub helpers: publish_session_event, publish_group_event
```

### Key Patterns to Be Aware Of

- **Two-queue SAQ design**: `orchestration` queue fans out work to the `checks` queue. Tasks receive a `ctx` dict containing `session_factory` (async DB session maker) and `redis` (Redis client).
- **Fully async**: ~75+ `async def` functions. All DB access via `AsyncSession`, HTTP via `httpx.AsyncClient`, concurrency via `asyncio.gather()` and `asyncio.Semaphore`.
- **Engine at import time**: `database.py` creates the SQLAlchemy async engine at module load. Tests must set env vars or mock before importing.
- **Redis Pub/Sub for SSE**: Routes subscribe to Redis channels for real-time streaming; tasks publish events on session/group progress.
- **Row-level locking**: Session finalization uses `SELECT ... FOR UPDATE` to prevent race conditions.
- **SSRF protection**: `utils.py` validates URLs against an `ALLOWED_URL_PATTERNS` hostname allowlist.

---

## Testing Strategy

Follow a **testing pyramid** approach, prioritizing test layers by ROI:

### Layer 1: Unit Tests (highest priority, fastest feedback)

Target pure functions and isolated logic with no external dependencies.

| Module | What to Test |
|--------|-------------|
| `utils.py` | `extract_guids()`, `extract_urls()`, `is_url_allowed()`, `normalize_url()`, `sanitize_error()`, `make_display_label()`, GUID regex patterns, edge cases (empty input, malformed URLs, unicode) |
| `schemas.py` | Pydantic model validation — required fields, defaults, coercion, rejection of invalid input, serialization round-trips |
| `models.py` | Model instantiation, JSON helper methods, default values, field constraints |
| `config.py` | Config parsing from env vars, default fallbacks, URL construction (`get_async_db_url`, `get_sync_db_url`) |
| `_serializers.py` | Serialization output format, null handling, optional field behavior |
| `tasks/events.py` | Event payload construction (mock the Redis client) |

**Mocking guidance**: These tests should need zero mocks for pure functions. For `config.py`, use `monkeypatch.setenv()`. For `events.py`, mock only the Redis `publish` call.

### Layer 2: Service Tests (medium priority)

Test service-layer business logic with mocked or in-memory dependencies.

| Module | What to Test | Dependency Strategy |
|--------|-------------|---------------------|
| `check_service.py` | Two-tier health check logic (nookbag + Antora fallback), timeout handling, SSL verification, error categorization, HTTP status interpretation | Mock `httpx.AsyncClient` responses using `respx` or `httpx.MockTransport` |
| `session_service.py` | Session CRUD, target resolution, finalization logic, stale session cleanup, pagination | Real async SQLite or PostgreSQL via testcontainers; mock SAQ queue |
| `babylon_service.py` | GUID resolution, workshop lookup, resource pool expansion, error handling for missing/partial K8s resources | Mock `babylon_client` functions to return fixture K8s API responses |
| `babylon_client.py` | Kubeconfig parsing, client creation, K8s API request construction, error handling | Mock `httpx.AsyncClient`; use fixture kubeconfig files |

### Layer 3: Route / Integration Tests (medium priority)

Test API endpoints end-to-end through FastAPI's `TestClient` (or `httpx.ASGITransport`).

| Module | What to Test |
|--------|-------------|
| `routes/health.py` | `/ping` returns 200, `/health` checks DB + Redis connectivity, `/config/clusters` returns cluster list |
| `routes/sessions.py` | Session creation (valid/invalid input), listing with pagination, detail fetch, clone, pin toggle, delete, SSE stream connection |
| `routes/groups.py` | Group creation, member management (add/remove), run triggering, metadata sync, SSE stream |
| `routes/check.py` | Deep-link query param parsing, redirect behavior, error handling for missing/invalid params |

**Setup**: Use `httpx.AsyncClient` with `ASGITransport(app=app)` for async test support. Override FastAPI dependencies (`app.dependency_overrides`) to inject test DB sessions and mock queues.

### Layer 4: Task Tests (medium-high priority)

SAQ tasks are critical business logic. Test them by constructing a mock `ctx` dict.

| Module | What to Test |
|--------|-------------|
| `tasks/orchestration.py` | `run_session_checks` — target resolution, fan-out to checks queue, error handling; `run_group` — session creation per member, parallel execution; `sweep_stale_sessions` — correct identification and cleanup of stale sessions |
| `tasks/checks.py` | `check_target` — delegates to `check_service`, writes results to DB, publishes events, handles finalization |

**Mock `ctx` pattern**:
```python
ctx = {
    "session_factory": test_session_factory,
    "redis": mock_redis,
    "orchestration_queue": mock_queue,
    "checks_queue": mock_queue,
}
```

### Layer 5: Database Migration Tests (low priority, high value)

- Verify Alembic migrations run forward cleanly against a fresh database.
- Verify the migration chain has no gaps (`alembic check` or `alembic heads` shows single head).
- Optionally test downgrade paths for recent migrations.

---

## Test Infrastructure Requirements

### Dependencies to Add

Add these to `pyproject.toml` under `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
dev = ["ruff"]
test = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "pytest-xdist>=3.5",       # parallel test execution
    "coverage[toml]>=7.0",
    "httpx",                    # already a runtime dep, needed for TestClient
    "respx>=0.22",              # httpx mock/intercept
    "factory-boy>=3.3",         # model factories (optional)
    "faker>=30.0",              # realistic test data (optional)
    "testcontainers[postgres]>=4.0",  # real PostgreSQL for integration tests
    "aiosqlite>=0.20",          # lightweight async DB for unit tests
]
```

### pytest Configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "unit: Pure unit tests, no external dependencies",
    "service: Service-layer tests with mocked dependencies",
    "integration: Tests requiring database or Redis",
    "slow: Tests that take >5s (testcontainers, migration checks)",
]
filterwarnings = [
    "ignore::DeprecationWarning:sqlalchemy.*",
]
```

### Coverage Configuration

Add to `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["soundcheck"]
branch = true
omit = [
    "soundcheck/__init__.py",
    "soundcheck/worker.py",
    "alembic/*",
]

[tool.coverage.report]
fail_under = 60
show_missing = true
skip_empty = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "if __name__ == .__main__.:",
    "@overload",
]

[tool.coverage.html]
directory = "htmlcov"
```

### Directory Structure

```
backend/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures: async DB, mock Redis, test app, factories
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_utils.py
│   │   ├── test_schemas.py
│   │   ├── test_models.py
│   │   ├── test_config.py
│   │   └── test_serializers.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── test_check_service.py
│   │   ├── test_session_service.py
│   │   ├── test_babylon_service.py
│   │   └── test_babylon_client.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── test_health.py
│   │   ├── test_sessions.py
│   │   ├── test_groups.py
│   │   └── test_check.py
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── test_orchestration.py
│   │   ├── test_checks.py
│   │   └── test_events.py
│   └── fixtures/
│       ├── k8s_responses.py     # Sample K8s API response dicts
│       └── check_responses.py   # Sample HTTP health check responses
```

---

## Core Fixtures (conftest.py)

Build these essential fixtures. Each fixture should be documented with a docstring explaining its scope and cleanup behavior.

### Async Database Session (for unit/service tests)

Use an in-memory SQLite with `aiosqlite` for fast, isolated tests. For integration tests needing PostgreSQL-specific features (JSON columns, `FOR UPDATE`), use `testcontainers`.

```python
@pytest_asyncio.fixture
async def db_session():
    """Async SQLAlchemy session against a fresh in-memory SQLite database."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()
```

### FastAPI Test Client

```python
@pytest_asyncio.fixture
async def client(db_session, mock_redis):
    """httpx AsyncClient wired to the FastAPI app with overridden dependencies."""
    from soundcheck.main import app
    from soundcheck.database import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
```

### Mock Redis

```python
@pytest.fixture
def mock_redis():
    """Mock Redis client with pub/sub support."""
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value=1)
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    return redis
```

### Mock SAQ Queue

```python
@pytest.fixture
def mock_queue():
    """Mock SAQ queue that captures enqueued jobs."""
    queue = AsyncMock()
    queue.enqueue = AsyncMock(return_value=MagicMock(id="test-job-id"))
    queue.map = AsyncMock(return_value=[])
    queue.apply = AsyncMock(return_value=None)
    return queue
```

### SAQ Task Context

```python
@pytest.fixture
def task_ctx(db_session, mock_redis, mock_queue):
    """Mock SAQ worker context dict matching TaskContext TypedDict."""
    return {
        "session_factory": AsyncMock(return_value=db_session),
        "redis": mock_redis,
        "orchestration_queue": mock_queue,
        "checks_queue": mock_queue,
    }
```

---

## Running Tests

### Commands

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov --cov-report=term-missing --cov-report=html

# Run only unit tests (fast, no external deps)
pytest -m unit

# Run service tests
pytest -m service

# Run integration tests (requires Docker for testcontainers)
pytest -m integration

# Run tests in parallel (requires pytest-xdist)
pytest -n auto

# Run a specific test file
pytest tests/unit/test_utils.py -v

# Run with verbose failure output
pytest --tb=long -v
```

### Makefile Targets

Add to the project `Makefile`:

```makefile
test:
	cd backend && python -m pytest

test-unit:
	cd backend && python -m pytest -m unit

test-cov:
	cd backend && python -m pytest --cov --cov-report=term-missing --cov-report=html

test-ci:
	cd backend && python -m pytest --cov --cov-report=xml --cov-fail-under=60 -m "not slow" --tb=short -q
```

---

## Metrics to Check and Report

After writing and running tests, report the following metrics:

### 1. Coverage Metrics

Run `pytest --cov --cov-report=term-missing` and report:

| Metric | Target | Description |
|--------|--------|-------------|
| **Overall line coverage** | >= 60% (initial), >= 80% (goal) | Percentage of source lines executed |
| **Branch coverage** | >= 50% (initial), >= 70% (goal) | Percentage of conditional branches taken |
| **Per-module coverage** | Report each | Identify modules with < 50% coverage for prioritization |
| **Uncovered lines** | List top 10 | Most impactful uncovered code paths |

### 2. Test Suite Health

| Metric | How to Check | Target |
|--------|-------------|--------|
| **Total test count** | `pytest --co -q \| tail -1` | >= 50 for initial suite |
| **Pass rate** | `pytest` exit code + summary | 100% pass |
| **Test duration** | `pytest --durations=10` | Unit tests < 0.1s each, full suite < 60s |
| **Flaky tests** | Run `pytest --count=3` (with `pytest-repeat`) | 0 flaky tests |
| **Warnings** | `pytest -W error::UserWarning` | 0 test warnings |

### 3. Test Distribution

Report the breakdown across test layers:

| Layer | Count | % of Total |
|-------|-------|-----------|
| Unit tests (`-m unit`) | — | Target: >= 50% |
| Service tests (`-m service`) | — | Target: >= 25% |
| Route/integration tests (`-m integration`) | — | Target: >= 20% |
| Task tests | — | Target: >= 5% |

### 4. Coverage Gaps Analysis

Identify and flag:

- **Untested modules**: Any module under `soundcheck/` with 0% coverage
- **Critical untested paths**: Error handlers, edge cases in finalization logic, SSRF validation bypasses
- **Dead code**: Code that coverage reveals is unreachable

### 5. Mutation Testing (optional, advanced)

If `mutmut` or `cosmic-ray` is installed:

```bash
mutmut run --paths-to-mutate=soundcheck/utils.py
mutmut results
```

Report the **mutation score** (% of mutants killed). Target >= 70% for `utils.py` and `check_service.py`.

---

## Test Quality Standards

Every test you write must follow these standards:

### Naming Convention

```
test_{function_or_feature}_{scenario}_{expected_outcome}
```

Examples:
- `test_extract_guids_with_valid_input_returns_guid_list`
- `test_is_url_allowed_rejects_private_ip`
- `test_create_session_with_empty_urls_returns_422`

### Structure: Arrange-Act-Assert

Every test should clearly separate setup, execution, and verification. Keep each test focused on a single behavior.

### Async Test Pattern

```python
@pytest.mark.unit
async def test_example(db_session):
    # Arrange
    session = CheckSession(name="test", status="pending")
    db_session.add(session)
    await db_session.commit()

    # Act
    result = await some_function(db_session)

    # Assert
    assert result.status == "completed"
```

### What NOT to Test

- SQLModel/SQLAlchemy internals (trust the ORM)
- FastAPI framework behavior (routing, dependency injection mechanics)
- Third-party library correctness (httpx, Redis client)
- Alembic migration SQL generation

### What to ALWAYS Test

- Input validation boundaries (empty, null, too-long, special characters, unicode)
- Error paths (network failures, timeouts, missing data, malformed responses)
- Status transitions (pending -> running -> completed/failed/error)
- Concurrency edge cases (double-finalization, stale session detection)
- Security-relevant logic (URL allowlist, GUID validation, API key checks)

---

## Execution Plan

Follow this order when building the test suite:

1. **Set up infrastructure**: Add test dependencies to `pyproject.toml`, create `tests/` directory structure, write `conftest.py` with core fixtures.

2. **Unit tests first** (`utils.py`, `schemas.py`, `config.py`): These are fast to write, need no mocks, and establish the testing pattern. Aim for >= 90% coverage on `utils.py`.

3. **Service tests** (`check_service.py`, then `session_service.py`): `check_service.py` is the most testable service — it has no DB dependency, just httpx calls. Use `respx` to mock HTTP responses. `session_service.py` needs the DB fixture.

4. **Task tests** (`tasks/checks.py`, `tasks/orchestration.py`): Build on the mock `ctx` fixture. Verify correct DB writes and queue interactions.

5. **Route tests** (`health.py`, then `sessions.py`, `groups.py`, `check.py`): Use the test client fixture. Verify HTTP status codes, response shapes, and that SAQ jobs are enqueued.

6. **Run coverage and report metrics**: Generate the coverage report, identify gaps, and document findings.

7. **Add CI integration**: Propose a GitHub Actions workflow step that runs `pytest --cov` on PRs.

---

## CI Integration

Propose adding a test job to `.github/workflows/lint.yaml` (or a new `test.yaml`):

```yaml
test-backend:
  runs-on: ubuntu-latest
  services:
    postgres:
      image: postgres:16
      env:
        POSTGRES_USER: test
        POSTGRES_PASSWORD: test
        POSTGRES_DB: test
      ports:
        - 5432:5432
      options: >-
        --health-cmd pg_isready
        --health-interval 10s
        --health-timeout 5s
        --health-retries 5
    redis:
      image: redis:7
      ports:
        - 6379:6379
      options: >-
        --health-cmd "redis-cli ping"
        --health-interval 10s
        --health-timeout 5s
        --health-retries 5
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: "3.12"
    - run: pip install -e ".[test]"
      working-directory: backend
    - run: pytest --cov --cov-report=xml --cov-fail-under=60 -m "not slow" --tb=short
      working-directory: backend
      env:
        DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/test
        REDIS_URL: redis://localhost:6379
        ALLOWED_URL_PATTERNS: "*.example.com"
    - uses: codecov/codecov-action@v4
      with:
        file: backend/coverage.xml
      if: always()
```

---

## Output Format

Structure your results as follows:

### Test Infrastructure Summary

What was set up: dependencies, configuration, fixtures, directory structure.

### Tests Written

For each test file, list:
- File path
- Number of tests
- Markers applied (`unit`, `service`, `integration`)
- Key scenarios covered

### Test Execution Results

```
========== N passed, M failed, K errors in X.XXs ==========
```

Include the full pytest summary output.

### Coverage Report

The `pytest --cov` output showing per-module coverage, plus a summary table:

| Module | Statements | Missed | Coverage | Branch Cov |
|--------|-----------|--------|----------|------------|
| `utils.py` | — | — | —% | —% |
| `schemas.py` | — | — | —% | —% |
| ... | | | | |
| **TOTAL** | — | — | —% | —% |

### Coverage Gaps & Recommendations

Prioritized list of untested code paths that should be covered next, with rationale.

### Test Quality Assessment

- Are tests independent? (no shared mutable state between tests)
- Are tests deterministic? (no reliance on system time, random data, or network)
- Are tests fast? (unit suite < 10s, full suite < 60s)
- Is the test-to-code ratio reasonable? (target >= 1:1 for critical modules)

### Failing Tests & Issues

Any tests that fail, with root cause analysis and suggested fixes.

### Recommended Next Steps

Prioritized list of testing improvements after the initial suite is in place.
