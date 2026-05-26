# Dead Code & Codebase Hygiene Audit

You are a senior software engineer performing a thorough codebase hygiene audit of the Showroom Soundcheck project. Your goal is to identify dead code, unused exports, orphaned files, stale comments, outdated documentation, and anything else that has drifted out of sync with the actual codebase.

## Codebase Overview

This is a two-part application:

- **Backend**: FastAPI + SQLModel + SAQ (async task queue) + Redis, located in `backend/soundcheck/`
- **Frontend**: SvelteKit 2 SPA with Svelte 5 runes and PatternFly v6 CSS, located in `frontend/src/`
- **Infrastructure**: Docker/Podman compose, OpenShift deploy manifests in `deploy/`, GitHub Actions in `.github/`, scripts in `scripts/`

### Backend Architecture

```
backend/soundcheck/
├── main.py              # FastAPI app, lifespan, CORS, router includes
├── config.py            # Env-var config
├── database.py          # Async engine, session factory
├── models.py            # SQLModel table models
├── schemas.py           # Pydantic request/response schemas
├── utils.py             # GUID extraction, URL allowlist, input validation
├── worker.py            # SAQ queue definitions, lifecycle hooks
├── routes/
│   ├── health.py        # GET /ping, /health, /config/clusters
│   ├── check.py         # GET /check (deep-link session creation)
│   ├── sessions.py      # Session CRUD, clone, run, SSE streaming
│   ├── groups.py        # Group CRUD, members, run, sync-metadata
│   └── _serializers.py  # Shared response serialization helpers
├── services/
│   ├── check_service.py  # Health check engine
│   ├── session_service.py # Session/group DB orchestration
│   ├── babylon_service.py # K8s GUID/Workshop/ResourcePool resolution
│   └── babylon_client.py  # httpx K8s API client manager
└── tasks/
    ├── __init__.py      # TaskContext TypedDict
    ├── orchestration.py # Coordinator tasks
    ├── checks.py        # Leaf task: check_target
    └── events.py        # Redis Pub/Sub helpers
```

### Frontend Architecture

```
frontend/src/
├── routes/
│   ├── +layout.svelte       # Root layout with sidebar
│   ├── +page.svelte          # Home page (new check / new group tabs)
│   ├── sessions/             # Session list
│   ├── sessions/new/         # Create session form
│   ├── session/[id]/         # Session detail with live SSE updates
│   ├── groups/               # Group list + create
│   ├── group/[id]/           # Group management + run history
│   └── check/                # Deep-link redirect
└── lib/
    ├── api.ts               # Typed API client
    ├── types.ts             # TypeScript types/interfaces
    └── components/          # Shared UI components
```

---

## Audit Dimensions

For each dimension, examine **every** relevant file. Report specific findings with file paths and line references.

---

### 1. Dead Code — Backend (Python)

Systematically check for:

- **Unused imports**: Modules imported but never referenced in the file. Pay attention to conditional imports, re-exports, and type-checking-only imports (`TYPE_CHECKING`).
- **Unused functions/methods**: Functions defined but never called from any other file or within the same file. Cross-reference call sites across the entire backend. Be careful with SAQ task functions registered by string name in `worker.py` — these are called by the queue, not directly.
- **Unused classes**: Classes defined but never instantiated or subclassed.
- **Unused Pydantic schemas**: Schemas in `schemas.py` that are never used as a `response_model`, request body type, or referenced elsewhere.
- **Unused SQLModel models or fields**: Table models or specific columns that are written but never read (or vice versa).
- **Unreachable code**: Code after unconditional `return`, `raise`, `break`, or `continue`. Branches that can never be true given the types involved.
- **Dead config variables**: Environment variables parsed in `config.py` but never read by any other module.
- **Commented-out code blocks**: Code left in comments that should either be restored or deleted.
- **Unused route parameters**: Path/query parameters declared in route signatures but never used in the function body.
- **Vestigial error handling**: `try`/`except` blocks that catch exceptions that can no longer be raised by the code they wrap.

### 2. Dead Code — Frontend (TypeScript/Svelte)

Systematically check for:

- **Unused imports**: Modules, components, types, or functions imported but never used.
- **Unused exported functions**: Functions exported from `api.ts`, `types.ts`, or utility modules that no component or route imports.
- **Unused types/interfaces**: Type definitions in `types.ts` that are never referenced.
- **Unused components**: `.svelte` files in `lib/components/` that are never imported by any route or other component.
- **Unused CSS classes**: Classes defined in `<style>` blocks that are never applied in the template. Note: PatternFly classes applied via string literals are used — only flag classes defined locally in component `<style>` blocks.
- **Dead reactive declarations**: `$derived`, `$state`, or `let` declarations that are assigned but never read in the template or script.
- **Unreachable template branches**: `{#if}` blocks whose condition can never be true, or `{:else}` blocks after conditions that are always true.
- **Commented-out code/markup**: HTML, script, or style blocks left in comments.
- **Unused event handlers**: Functions bound to events (`onclick`, `onsubmit`) that are defined but the binding has been removed, or vice versa.
- **Unused props**: Props declared via `$props()` destructuring but never used in the component body or template.

### 3. Orphaned & Unnecessary Files

- **Orphaned source files**: `.py`, `.ts`, `.svelte`, or `.js` files that exist on disk but are never imported, included, or referenced by any other file. Check if they are leftover from a refactor.
- **Stale migration files**: Alembic migrations in `backend/alembic/versions/` that are superseded or reference tables/columns that no longer exist. Note: don't flag migrations just for being old — only flag if they reference entities that have been removed.
- **Orphaned test files**: Test files (if any) that test functions/classes that no longer exist.
- **Stale config files**: Config files (`.eslintrc`, `tsconfig.json`, `pyproject.toml`, `ruff.toml`) with rules, paths, or plugins referencing things that no longer exist.
- **Unused static assets**: Images, fonts, or other static files in `frontend/static/` or `backend/` that are never referenced.
- **Leftover scaffolding**: Default SvelteKit/FastAPI boilerplate files that were never customized and serve no purpose.
- **Unused scripts**: Shell scripts in `scripts/` or npm scripts in `package.json` that reference commands, paths, or tools that no longer exist.
- **Unused dependencies**: Packages listed in `requirements.txt` or `package.json` that are never imported in the source code.
- **Stale Docker/compose artifacts**: Dockerfile stages, compose services, volumes, or environment variables that reference removed features.

### 4. Outdated Comments & Documentation

- **Stale inline comments**: Comments that describe behavior the code no longer exhibits. Examples:
  - Comments referencing function names, variable names, or class names that have been renamed.
  - Comments saying "TODO" or "FIXME" for issues that have already been resolved.
  - Comments describing a workaround for a bug that has since been fixed.
  - Comments explaining "why" something is done a certain way when the code now does it differently.
- **Outdated docstrings**: Function/class docstrings that list parameters, return types, or behaviors that don't match the current signature or implementation.
- **Stale TODOs**: `TODO`, `FIXME`, `HACK`, `XXX`, or `WORKAROUND` comments — for each one, evaluate whether the issue has been addressed, is still relevant, or refers to something that no longer exists.
- **README drift**: Check `README.md` against the actual codebase:
  - Are all listed environment variables still used?
  - Does the architecture diagram match the current file layout?
  - Are the listed commands (`make lint`, `make format`, etc.) still valid?
  - Do the listed URLs, ports, and service names match docker-compose?
  - Are features described that no longer exist, or missing features that do exist?
- **Stale API documentation**: If there are OpenAPI overrides, docstrings on routes, or external API docs, verify they match the current route signatures, request/response schemas, and behavior.
- **Outdated type annotations**: Type hints that don't match the actual runtime types (e.g., a function annotated as returning `str` but actually returns `dict`).

### 5. Unused API Surface

- **Dead API routes**: Routes registered in `main.py` or router includes that serve no purpose — either they duplicate another route's functionality, are never called by the frontend, or return data that nothing consumes.
- **Unused response fields**: Fields in response schemas that the frontend never reads. Cross-reference the Pydantic `response_model` fields with the frontend's `types.ts` interfaces and actual usage in `.svelte` files.
- **Unused request fields**: Fields in request body schemas that the backend accepts but ignores (never reads from the parsed body).
- **Vestigial query parameters**: Query parameters that a route accepts but no longer does anything with.
- **Dead SSE event types**: Event types published via Redis Pub/Sub that the frontend never listens for or handles.
- **Unused API client functions**: Functions in `frontend/src/lib/api.ts` that are exported but never called by any component or route.

### 6. Dependency Hygiene

- **Unused Python packages**: Packages in `requirements.txt` that are never imported anywhere in `backend/`.
- **Unused npm packages**: Packages in `frontend/package.json` (`dependencies` + `devDependencies`) that are never imported or referenced in config files.
- **Pinning issues**: Dependencies pinned to very old versions when newer versions are available and likely compatible. Note version constraints that may be stale.
- **Duplicate functionality**: Multiple packages installed that serve the same purpose (e.g., two HTTP clients, two date libraries).
- **Missing from manifest**: Packages actually imported in code but not listed in the dependency manifest (implicit transitive dependencies that could break on upgrade).

---

## Review Process

1. **Read every file** in `backend/soundcheck/`, `frontend/src/`, and project root config files.
2. For each finding, verify it by cross-referencing usages across the entire codebase — don't flag something as unused based on a single file in isolation.
3. Be careful with dynamic references: SAQ tasks referenced by string name, Svelte components auto-imported, `__all__` exports, and `TYPE_CHECKING` imports are NOT dead code.
4. For API surface analysis, check both sides: a backend route is only "dead" if the frontend doesn't call it AND there's no external consumer documented.

---

## Output Format

### Summary Statistics

Report counts: total dead code items found, broken down by category and severity.

### Issue Summary Table

| # | Category | Severity | Finding | File(s) |
|---|----------|----------|---------|---------|
| 1 | Dead Code | High | Unused schema `FooResponse` | `schemas.py` |
| 2 | Stale Comment | Medium | TODO resolved in commit abc123 | `services/check_service.py:45` |
| ... | ... | ... | ... | ... |

Severity levels: **High** (actively misleading or confusing), **Medium** (clutters the codebase), **Low** (minor noise).

### Detailed Findings

For each finding, provide:
- **File path and line number(s)**
- **What** is dead/stale/unused
- **Evidence**: how you confirmed it (e.g., "grepped for `FooResponse` across backend — zero references outside its definition")
- **Recommendation**: delete, update, or keep with justification

### Cleanup Checklist

A prioritized, actionable checklist of cleanup tasks ordered by impact. Group related items (e.g., "remove 4 unused schemas from `schemas.py`" rather than listing each individually). Each item should be a single PR-sized change.

### Positive Observations

Note areas where the codebase is already clean — well-maintained docs, no dead imports, etc.
