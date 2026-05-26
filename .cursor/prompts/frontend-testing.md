# Frontend Testing Agent Prompt

You are an expert frontend test engineer specializing in **Svelte 5**, **SvelteKit 2**, **Vitest**, **Svelte Testing Library**, **Playwright**, and **production-grade test architecture**. Your task is to create and verify a comprehensive test suite for the Showroom Soundcheck frontend located at `frontend/`.

## Codebase Overview

This is a **Svelte 5 / SvelteKit 2 single-page application** that provides a dashboard for monitoring health checks against "showroom" lab environments. It deploys as a static SPA behind a Node.js reverse proxy.

### Tech Stack

| Category | Technology |
|----------|------------|
| Language | TypeScript 5 (strict mode) |
| Framework | Svelte 5 (runes: `$state`, `$derived`, `$effect`, `$props`) |
| Meta-framework | SvelteKit 2 (`@sveltejs/kit`) |
| Build tool | Vite 6 |
| Adapter | `@sveltejs/adapter-static` (SPA with `fallback: 'index.html'`, SSR disabled) |
| UI / CSS | PatternFly v6 (CSS-only, no component library) |
| Fonts | Red Hat fonts (RedHatText, RedHatDisplay, RedHatMono) |
| Data fetching | Custom `fetch`-based REST client (`$lib/api.ts`) |
| Real-time | `EventSource` SSE streams for live session/group updates |
| State management | Svelte 5 runes (local component state only, no global store) |
| Linting | ESLint + `eslint-plugin-svelte` |
| Formatting | Prettier + `prettier-plugin-svelte` |
| Type checking | `svelte-check` |

### Architecture

```
frontend/src/
├── app.html                         # HTML shell, loads PatternFly CSS
├── lib/
│   ├── api.ts                       # REST client: fetchJson<T>(), all API functions, EventSource streams
│   ├── types.ts                     # TypeScript interfaces + statusColor() helper
│   ├── utils.ts                     # relativeTime() helper
│   ├── actions/
│   │   ├── focusTrap.ts             # Svelte action: keyboard focus trap for modals
│   │   └── portal.ts               # Svelte action: portal DOM node to document.body
│   └── components/
│       ├── GroupRunHistory.svelte    # Group run history table
│       ├── GroupSourceList.svelte    # Group source management UI
│       ├── Modal.svelte             # Accessible modal dialog (uses focusTrap + portal)
│       ├── SessionContent.svelte    # Session detail + live streaming (~928 lines, largest component)
│       ├── SessionDrawer.svelte     # Session detail side drawer
│       ├── Sidebar.svelte           # App navigation sidebar
│       ├── Spinner.svelte           # Loading spinner
│       ├── StatusBadge.svelte       # Color-coded status indicator
│       ├── TableSkeleton.svelte     # Loading skeleton for tables
│       └── TargetDetail.svelte      # Individual target check result detail
└── routes/                          # SvelteKit file-based routing
    ├── +layout.js                   # export const ssr = false
    ├── +layout.svelte               # App shell: masthead, sidebar, PatternFly page layout
    ├── +page.ts / +page.svelte      # Redirect / → /sessions
    ├── +error.svelte                # Error page
    ├── check/+page.svelte           # Query-param redirect → session
    ├── session/[id]/+page.svelte    # Session detail (uses SessionContent)
    ├── sessions/
    │   ├── +page.ts                 # load: listSessions()
    │   ├── +page.svelte             # Sessions list (paginated, searchable)
    │   └── new/+page.svelte         # Create session form
    ├── group/[id]/+page.svelte      # Group detail
    ├── groups/
    │   ├── +page.ts                 # load: listGroups()
    │   ├── +page.svelte             # Groups list
    │   └── new/+page.svelte         # Create group form
    └── ...
```

### Key Patterns to Be Aware Of

- **Svelte 5 runes everywhere**: Components use `$state`, `$state.raw`, `$derived`, `$derived.by`, `$effect`, and `$props` — **not** legacy `$:` reactive declarations or `svelte/store`.
- **SSR disabled globally**: `+layout.js` exports `ssr = false`. All `load` functions run client-side.
- **PatternFly CSS classes**: Components render PatternFly v6 class names (e.g. `pf-v6-c-page`, `pf-v6-c-button`, `pf-m-primary`) but there is no PatternFly component library — all markup is hand-written.
- **Custom Svelte actions**: `focusTrap` and `portal` are Svelte actions used by `Modal.svelte` for accessibility and DOM portaling.
- **API proxy**: In dev, Vite proxies `/api` to the backend. In production, a Node.js server handles the proxy. Tests must mock `/api` calls.
- **EventSource SSE**: `sessionStream()` and `groupStream()` return browser `EventSource` instances for real-time updates.
- **No global state**: All state lives in components via runes. Data flows from `load` functions → page components → child components via `$props`.

---

## Testing Strategy

Follow a **testing trophy** approach (unit → integration → E2E), prioritizing integration tests for the most value:

### Layer 1: Unit Tests (highest priority, fastest feedback)

Target pure functions and isolated logic with no DOM or component dependencies.

| Module | What to Test |
|--------|-------------|
| `lib/utils.ts` | `relativeTime()` — "just now", minutes, hours, days thresholds; edge cases (future dates, invalid strings, epoch) |
| `lib/types.ts` | `statusColor()` — every `Status` variant maps to the correct `StatusColor`; exhaustiveness |
| `lib/api.ts` | `fetchJson()` — success parsing, error extraction (`detail`, `message`, fallback), non-JSON error bodies; `listSessions()` / `listGroups()` — query string construction from `ListParams`; `removeGroupSource()` — URI encoding of path params |

**Mocking guidance**: Use `vi.fn()` / `vi.spyOn()` to mock `globalThis.fetch` for `api.ts` tests. For `utils.ts` and `types.ts`, no mocks needed — these are pure functions.

### Layer 2: Component Tests (medium-high priority)

Test Svelte components in a jsdom/happy-dom environment using Svelte Testing Library.

| Component | What to Test |
|-----------|-------------|
| `StatusBadge.svelte` | Renders correct label and color class for each `Status` value; respects `size` prop (`sm`/`md`); correct SVG icon per status |
| `Spinner.svelte` | Renders loading indicator |
| `Modal.svelte` | Renders title, body content via snippet; closes on Escape key; closes on backdrop click; does not close on inner click (stopPropagation); focus trap works (Tab/Shift+Tab cycles within modal); portals to document.body |
| `TableSkeleton.svelte` | Renders correct number of skeleton rows |
| `Sidebar.svelte` | Renders navigation links; active link highlighted; collapse/expand toggle |
| `SessionContent.svelte` | Fetches and renders session data; shows loading state; handles API errors; renders targets list; status transitions on SSE events (mock EventSource) |
| `TargetDetail.svelte` | Renders target info (URL, status, response time); displays check results; handles null/missing fields |
| `GroupSourceList.svelte` | Renders source list; add/remove source interactions |
| `GroupRunHistory.svelte` | Renders run history table; status badges per run |

**Mocking guidance**:
- Mock `$lib/api` module (`vi.mock('$lib/api')`) to control API responses
- Mock `EventSource` globally for SSE streaming tests
- Use `@testing-library/svelte` `render()` and `@testing-library/user-event` for interactions
- For `Modal.svelte`, test the focus trap and portal behaviors with DOM assertions

### Layer 3: Route / Page Integration Tests (medium priority)

Test full page components with mocked API layer.

| Route | What to Test |
|-------|-------------|
| `/sessions` | Renders session list from loaded data; pagination controls work (next/prev/page size); search filters results; delete triggers confirmation dialog; pin toggle calls API; row click navigates to session detail |
| `/sessions/new` | Form validation (empty URL list, invalid URLs); successful submission navigates to new session; error display on API failure |
| `/groups` | Group list rendering; pagination; search; delete with confirmation |
| `/groups/new` | Form validation; group creation; error handling |
| `/session/[id]` | Loads and renders session detail; SSE stream updates UI in real-time; clone/delete/re-run actions |
| `/group/[id]` | Loads group detail; run history display; source management; SSE updates |
| `/check` | Query parameter parsing; redirect to correct session; error handling for invalid params |
| `/` | Redirects to `/sessions` |

### Layer 4: Svelte Action Tests (low priority, high value)

| Action | What to Test |
|--------|-------------|
| `focusTrap` | Tab wraps from last to first focusable element; Shift+Tab wraps from first to last; auto-focuses first focusable on mount; restores previous focus on destroy; handles zero focusable elements |
| `portal` | Appends node to `document.body` (or custom target); removes node on destroy |

### Layer 5: E2E Tests with Playwright (lowest priority, highest confidence)

End-to-end tests against the running app (dev server or preview build) with mocked API.

| Flow | What to Test |
|------|-------------|
| Session lifecycle | Create session → view running state → see results stream in → view completed state |
| Group management | Create group → add sources → run checks → view run history |
| Navigation | Sidebar navigation between sessions/groups; browser back/forward; deep links |
| Responsive layout | Sidebar collapses on mobile; tables scroll horizontally |
| Accessibility | Focus management in modals; keyboard navigation; ARIA attributes |

---

## Test Infrastructure Requirements

### Dependencies to Add

Add these to `frontend/package.json` under `devDependencies`:

```json
{
  "devDependencies": {
    "@testing-library/svelte": "^5.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "@testing-library/user-event": "^14.0.0",
    "vitest": "^3.0.0",
    "@vitest/coverage-v8": "^3.0.0",
    "jsdom": "^26.0.0",
    "@sveltejs/vite-plugin-svelte": "^5.0.0",
    "@playwright/test": "^1.50.0",
    "msw": "^2.0.0"
  }
}
```

| Package | Purpose |
|---------|---------|
| `vitest` | Test runner with native Vite integration — zero config for SvelteKit |
| `@vitest/coverage-v8` | V8-based code coverage (fast, accurate) |
| `@testing-library/svelte` | Render Svelte 5 components in tests, query DOM |
| `@testing-library/jest-dom` | Extended DOM matchers (`toBeVisible`, `toHaveTextContent`, etc.) |
| `@testing-library/user-event` | Simulate real user interactions (click, type, tab) |
| `jsdom` | DOM environment for unit/component tests |
| `@playwright/test` | E2E browser testing |
| `msw` | Mock Service Worker for intercepting `fetch`/`EventSource` in integration tests |

### Vitest Configuration

Create `frontend/vitest.config.ts`:

```typescript
import { defineConfig } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
  plugins: [sveltekit()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{js,ts}', 'tests/**/*.{test,spec}.{js,ts}'],
    setupFiles: ['tests/setup.ts'],
    globals: true,
    coverage: {
      provider: 'v8',
      include: ['src/lib/**/*.{ts,svelte}', 'src/routes/**/*.{ts,svelte}'],
      exclude: [
        'src/lib/types.ts',
        'src/**/*.d.ts',
        'src/app.html',
      ],
      reporter: ['text', 'text-summary', 'html', 'lcov'],
      branches: 50,
      functions: 50,
      lines: 60,
      statements: 60,
    },
    alias: {
      '$lib': '/src/lib',
      '$app/navigation': '/tests/mocks/app-navigation.ts',
      '$app/state': '/tests/mocks/app-state.ts',
    },
  },
});
```

### Test Setup File

Create `frontend/tests/setup.ts`:

```typescript
import '@testing-library/jest-dom/vitest';
```

### SvelteKit Module Mocks

SvelteKit provides `$app/*` modules that must be mocked in unit/component tests.

Create `frontend/tests/mocks/app-navigation.ts`:

```typescript
import { vi } from 'vitest';
export const goto = vi.fn();
export const invalidate = vi.fn();
export const invalidateAll = vi.fn();
export const beforeNavigate = vi.fn();
export const afterNavigate = vi.fn();
```

Create `frontend/tests/mocks/app-state.ts`:

```typescript
export const page = {
  url: new URL('http://localhost'),
  params: {},
  route: { id: '/' },
  status: 200,
  error: null,
  data: {},
};
```

### npm Scripts

Add to `frontend/package.json`:

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage",
    "test:ui": "vitest --ui",
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui"
  }
}
```

### Playwright Configuration

Create `frontend/playwright.config.ts`:

```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'html',
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 5'] } },
  ],
  webServer: {
    command: 'npm run build && npm run preview',
    port: 4173,
    reuseExistingServer: !process.env.CI,
  },
});
```

### Directory Structure

```
frontend/
├── vitest.config.ts
├── playwright.config.ts
├── tests/
│   ├── setup.ts                       # Global test setup (jest-dom matchers)
│   ├── mocks/
│   │   ├── app-navigation.ts          # Mock $app/navigation
│   │   ├── app-state.ts               # Mock $app/state
│   │   ├── api.ts                     # Shared API mock helpers / fixtures
│   │   └── eventsource.ts            # Mock EventSource for SSE tests
│   ├── unit/
│   │   ├── utils.test.ts              # relativeTime() tests
│   │   ├── types.test.ts             # statusColor() tests
│   │   ├── api.test.ts               # fetchJson(), query string construction
│   │   └── actions.test.ts           # focusTrap, portal action tests
│   ├── components/
│   │   ├── StatusBadge.test.ts        # StatusBadge rendering tests
│   │   ├── Modal.test.ts             # Modal interactions, a11y, focus trap
│   │   ├── Spinner.test.ts           # Spinner rendering
│   │   ├── TableSkeleton.test.ts     # TableSkeleton rendering
│   │   ├── Sidebar.test.ts           # Navigation, active state
│   │   ├── SessionContent.test.ts    # Session detail + SSE streaming
│   │   ├── TargetDetail.test.ts      # Target result display
│   │   ├── GroupSourceList.test.ts   # Source CRUD interactions
│   │   └── GroupRunHistory.test.ts   # Run history table
│   └── routes/
│       ├── sessions.test.ts           # Sessions list page
│       ├── sessions-new.test.ts       # Create session page
│       ├── session-detail.test.ts     # Session detail page
│       ├── groups.test.ts             # Groups list page
│       ├── groups-new.test.ts         # Create group page
│       ├── group-detail.test.ts       # Group detail page
│       └── check.test.ts             # Check redirect page
├── e2e/
│   ├── sessions.spec.ts              # Session lifecycle E2E
│   ├── groups.spec.ts                # Group management E2E
│   ├── navigation.spec.ts            # App navigation E2E
│   └── accessibility.spec.ts         # Keyboard + screen reader E2E
```

---

## Core Test Helpers & Fixtures

### API Mock Helpers

Create `frontend/tests/mocks/api.ts`:

```typescript
import type {
  SessionListItem, SessionDetail, SessionPublic,
  TargetPublic, CheckResultPublic,
  GroupListItem, GroupDetail, GroupPublic, GroupRunPublic,
  PaginatedResponse
} from '$lib/types';

export function mockSessionListItem(overrides: Partial<SessionListItem> = {}): SessionListItem {
  return {
    id: 1,
    session_id: 'test-session-001',
    name: 'Test Session',
    group_id: null,
    display_label: 'test-session',
    status: 'completed',
    pinned: false,
    created_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    resource_display_name: 'Test Resource',
    source_id: 'test-source',
    ...overrides,
  };
}

export function mockSessionDetail(overrides: Partial<SessionPublic> = {}): SessionDetail {
  return {
    session: {
      id: 1,
      session_id: 'test-session-001',
      name: 'Test Session',
      group_id: null,
      group_run_id: null,
      check_type: 'readyz',
      source_urls: ['https://example.com'],
      source_guids: [],
      source_workshop_guids: [],
      source_resource_pools: [],
      babylon_cluster: 'default',
      display_label: 'test-session',
      status: 'completed',
      pinned: false,
      created_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
      resource_name: 'test',
      resource_namespace: 'default',
      resource_kind: 'AnarchySubject',
      resource_display_name: 'Test Resource',
      resource_metadata: {},
      ...overrides,
    },
    targets: [],
    results: [],
  };
}

export function mockPaginatedResponse<T>(
  items: T[],
  overrides: Partial<PaginatedResponse<T>> = {}
): PaginatedResponse<T> {
  return {
    items,
    total: items.length,
    page: 1,
    per_page: 20,
    ...overrides,
  };
}

export function mockTarget(overrides: Partial<TargetPublic> = {}): TargetPublic {
  return {
    id: 1,
    session_id: 'test-session-001',
    url: 'https://example.com',
    label: 'example.com',
    guid: null,
    workshop_guid: null,
    resource_pool_name: null,
    resource_name: 'test',
    resource_namespace: 'default',
    provision_status: null,
    status: 'healthy',
    tier_used: 1,
    response_time_ms: 150,
    error_message: null,
    check_started_at: new Date().toISOString(),
    check_completed_at: new Date().toISOString(),
    ...overrides,
  };
}
```

### EventSource Mock

Create `frontend/tests/mocks/eventsource.ts`:

```typescript
import { vi } from 'vitest';

export class MockEventSource {
  url: string;
  readyState = 0;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;
  close = vi.fn();

  private listeners: Record<string, ((event: MessageEvent) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    this.readyState = 1; // OPEN
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void) {
    if (!this.listeners[type]) return;
    this.listeners[type] = this.listeners[type].filter((l) => l !== listener);
  }

  simulateMessage(data: unknown, event = 'message') {
    const messageEvent = new MessageEvent(event, {
      data: typeof data === 'string' ? data : JSON.stringify(data),
    });
    if (event === 'message' && this.onmessage) {
      this.onmessage(messageEvent);
    }
    this.listeners[event]?.forEach((l) => l(messageEvent));
  }

  simulateError() {
    this.readyState = 2; // CLOSED
    if (this.onerror) this.onerror(new Event('error'));
  }
}

export function installMockEventSource() {
  const instances: MockEventSource[] = [];
  const original = globalThis.EventSource;

  (globalThis as unknown as Record<string, unknown>).EventSource = class extends MockEventSource {
    constructor(url: string) {
      super(url);
      instances.push(this);
    }
  };

  return {
    instances,
    restore: () => {
      (globalThis as unknown as Record<string, unknown>).EventSource = original;
    },
  };
}
```

### Fetch Mock Helper

For `api.ts` unit tests, mock `globalThis.fetch`:

```typescript
export function mockFetch(response: unknown, options: { ok?: boolean; status?: number } = {}) {
  const { ok = true, status = 200 } = options;
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue({
    ok,
    status,
    json: () => Promise.resolve(response),
  } as Response);
}
```

---

## Running Tests

### Commands

```bash
# Run all unit + component tests
npm test

# Run in watch mode during development
npm run test:watch

# Run with coverage report
npm run test:coverage

# Run with Vitest UI (browser-based test explorer)
npm run test:ui

# Run only unit tests
npx vitest run tests/unit/

# Run only component tests
npx vitest run tests/components/

# Run a specific test file
npx vitest run tests/unit/utils.test.ts

# Run tests matching a name pattern
npx vitest run -t "relativeTime"

# Run E2E tests (requires app build)
npm run test:e2e

# Run E2E with interactive UI
npm run test:e2e:ui

# Run E2E for a specific browser
npx playwright test --project=chromium

# Debug a specific E2E test
npx playwright test e2e/sessions.spec.ts --debug
```

---

## Metrics to Check and Report

After writing and running tests, report the following metrics:

### 1. Coverage Metrics

Run `npm run test:coverage` and report:

| Metric | Target | Description |
|--------|--------|-------------|
| **Overall line coverage** | >= 60% (initial), >= 80% (goal) | Percentage of source lines executed |
| **Branch coverage** | >= 50% (initial), >= 70% (goal) | Percentage of conditional branches taken |
| **Function coverage** | >= 50% (initial), >= 75% (goal) | Percentage of functions called |
| **Per-module coverage** | Report each | Identify modules with < 50% coverage for prioritization |
| **Uncovered lines** | List top 10 | Most impactful uncovered code paths |

### 2. Test Suite Health

| Metric | How to Check | Target |
|--------|-------------|--------|
| **Total test count** | `npx vitest run --reporter=verbose 2>&1 \| tail -5` | >= 40 for initial suite |
| **Pass rate** | Vitest exit code + summary | 100% pass |
| **Test duration** | Vitest summary output | Unit tests < 50ms each, full suite < 30s |
| **Flaky tests** | Run `npx vitest run --retry=3` | 0 flaky tests |
| **Type errors** | `npm run check` | 0 type errors in test files |

### 3. Test Distribution

Report the breakdown across test layers:

| Layer | Count | % of Total |
|-------|-------|-----------|
| Unit tests (`tests/unit/`) | — | Target: >= 40% |
| Component tests (`tests/components/`) | — | Target: >= 35% |
| Route/page tests (`tests/routes/`) | — | Target: >= 20% |
| E2E tests (`e2e/`) | — | Target: >= 5% |

### 4. Coverage Gaps Analysis

Identify and flag:

- **Untested modules**: Any module under `src/lib/` or `src/routes/` with 0% coverage
- **Critical untested paths**: Error handlers, loading states, SSE reconnection, edge cases in form validation
- **Unreachable code**: Code that coverage reveals is never executed
- **Component interaction gaps**: Props combinations or user flows that are untested

### 5. Accessibility Audit

Run during component and E2E tests:

| Check | How | Target |
|-------|-----|--------|
| **ARIA attributes** | Assert `role`, `aria-label`, `aria-modal` on Modal, StatusBadge | All interactive elements labeled |
| **Keyboard navigation** | Test Tab/Shift+Tab/Escape in Modal, Sidebar | All features keyboard-accessible |
| **Focus management** | Assert focus moves correctly on modal open/close, page navigation | No focus traps (except intentional modal trap) |

### 6. Bundle Impact (optional, advanced)

After adding test dependencies, verify they don't leak into the production bundle:

```bash
npm run build
ls -lh build/_app/immutable/
```

Test deps (`vitest`, `@testing-library/*`, `jsdom`) must be in `devDependencies` only.

---

## Test Quality Standards

Every test you write must follow these standards:

### Naming Convention

```
describe('ModuleName') → it('should {expected behavior} when {scenario}')
```

Examples:
- `it('should return "just now" when date is less than 1 minute ago')`
- `it('should render green badge when status is healthy')`
- `it('should close modal when Escape key is pressed')`
- `it('should show error message when API call fails')`

### Structure: Arrange-Act-Assert

Every test should clearly separate setup, execution, and verification. Keep each test focused on a single behavior.

```typescript
it('should display error when session fetch fails', async () => {
  // Arrange
  vi.mocked(getSession).mockRejectedValue(new Error('Network error'));

  // Act
  render(SessionContent, { props: { sessionId: 'abc' } });
  await waitFor(() => screen.getByRole('alert'));

  // Assert
  expect(screen.getByRole('alert')).toHaveTextContent('Network error');
});
```

### Svelte 5 Component Testing Pattern

```typescript
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import StatusBadge from '$lib/components/StatusBadge.svelte';

describe('StatusBadge', () => {
  it('should render "Healthy" label with green styling for healthy status', () => {
    render(StatusBadge, { props: { status: 'healthy' } });

    const badge = screen.getByText('Healthy');
    expect(badge.closest('.status-badge')).toHaveClass('status-badge--green');
  });

  it('should render small size when size prop is "sm"', () => {
    render(StatusBadge, { props: { status: 'running', size: 'sm' } });

    const badge = screen.getByText('Running').closest('.status-badge');
    expect(badge).toHaveClass('status-badge--sm');
  });
});
```

### Async API Testing Pattern

```typescript
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

describe('fetchJson', () => {
  afterEach(() => vi.restoreAllMocks());

  it('should parse JSON response on success', async () => {
    const data = { session_id: 'abc' };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(data),
    } as Response);

    const { fetchJson } = await import('$lib/api');
    const result = await fetchJson('/api/test');

    expect(result).toEqual(data);
  });

  it('should throw with detail message on API error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: 'Invalid input' }),
    } as Response);

    const { fetchJson } = await import('$lib/api');
    await expect(fetchJson('/api/test')).rejects.toThrow('Invalid input');
  });
});
```

### What NOT to Test

- SvelteKit framework internals (routing mechanics, adapter behavior, SSR pipeline)
- Vite bundling or HMR behavior
- PatternFly CSS rendering fidelity (trust the CSS framework)
- Browser APIs that jsdom/happy-dom don't support well (IntersectionObserver, CSS animations)
- Third-party library correctness (`fetch`, `EventSource` implementations)

### What to ALWAYS Test

- **User interactions**: Click, type, keyboard shortcuts, form submissions
- **Loading states**: Skeleton/spinner shown while data fetches
- **Error states**: API failures show meaningful error messages
- **Empty states**: No items in list shows appropriate message
- **Accessibility**: ARIA attributes, keyboard navigation, focus management
- **Status transitions**: `pending` → `running` → `completed`/`failed` via SSE events
- **Input validation**: Empty fields, invalid URLs, boundary values
- **Conditional rendering**: Different UI for different data shapes (null fields, empty arrays)

---

## Execution Plan

Follow this order when building the test suite:

1. **Set up infrastructure**: Install test dependencies, create `vitest.config.ts`, `tests/setup.ts`, mock files, and directory structure. Verify `npm test` runs with zero tests.

2. **Unit tests first** (`utils.ts`, `types.ts`, `api.ts`): Pure functions, no DOM needed. Establishes the testing pattern and catches regressions fast. Aim for >= 95% coverage on `utils.ts` and `types.ts`.

3. **Simple component tests** (`StatusBadge`, `Spinner`, `TableSkeleton`, `Modal`): Small, self-contained components. Validates the Svelte Testing Library setup works. Tests props, rendering, and basic interactions.

4. **Action tests** (`focusTrap`, `portal`): These are pure DOM manipulations — test them directly against jsdom elements without Svelte components.

5. **Complex component tests** (`SessionContent`, `Sidebar`, `GroupSourceList`): Requires API mocking and EventSource mocking. Tests data flow, user interactions, and error handling.

6. **Route/page tests** (`sessions`, `groups`, `check`): Full page render with mocked API. Tests pagination, search, navigation, and form submission.

7. **E2E tests** (Playwright): Full browser tests against running app. Covers critical user journeys end-to-end.

8. **Run coverage and report metrics**: Generate the coverage report, identify gaps, and document findings.

---

## CI Integration

Propose adding a test job to `.github/workflows/lint.yaml` (or a new `test.yaml`):

```yaml
test-frontend:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: '22'
        cache: 'npm'
        cache-dependency-path: frontend/package-lock.json
    - run: npm ci
      working-directory: frontend
    - run: npm run check
      working-directory: frontend
    - run: npm run test:coverage
      working-directory: frontend
    - uses: codecov/codecov-action@v4
      with:
        file: frontend/coverage/lcov.info
        flags: frontend
      if: always()

test-frontend-e2e:
  runs-on: ubuntu-latest
  needs: [test-frontend]
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: '22'
        cache: 'npm'
        cache-dependency-path: frontend/package-lock.json
    - run: npm ci
      working-directory: frontend
    - run: npx playwright install --with-deps chromium
      working-directory: frontend
    - run: npm run test:e2e -- --project=chromium
      working-directory: frontend
    - uses: actions/upload-artifact@v4
      with:
        name: playwright-report
        path: frontend/playwright-report/
      if: always()
```

---

## Output Format

Structure your results as follows:

### Test Infrastructure Summary

What was set up: dependencies installed, configuration files created, mocks written, directory structure.

### Tests Written

For each test file, list:
- File path
- Number of tests
- Layer (`unit`, `component`, `route`, `e2e`)
- Key scenarios covered

### Test Execution Results

```
✓ tests/unit/utils.test.ts (N tests)
✓ tests/unit/types.test.ts (N tests)
✓ tests/components/StatusBadge.test.ts (N tests)
...
Test Files  X passed (X)
Tests       Y passed (Y)
Duration    Z.ZZs
```

Include the full Vitest summary output.

### Coverage Report

The `npm run test:coverage` output showing per-module coverage, plus a summary table:

| Module | Statements | Branches | Functions | Lines | Uncovered Lines |
|--------|-----------|----------|-----------|-------|-----------------|
| `lib/utils.ts` | —% | —% | —% | —% | — |
| `lib/types.ts` | —% | —% | —% | —% | — |
| `lib/api.ts` | —% | —% | —% | —% | — |
| ... | | | | | |
| **TOTAL** | —% | —% | —% | —% | — |

### Coverage Gaps & Recommendations

Prioritized list of untested code paths that should be covered next, with rationale.

### Test Quality Assessment

- Are tests independent? (no shared mutable state between tests)
- Are tests deterministic? (no reliance on real `Date.now()`, network, or random data)
- Are tests fast? (unit suite < 5s, component suite < 15s, full suite < 30s)
- Do tests follow Testing Library best practices? (query by role/label, not CSS selectors)
- Is the test-to-code ratio reasonable? (target >= 1:1 for critical modules)

### Failing Tests & Issues

Any tests that fail, with root cause analysis and suggested fixes.

### Recommended Next Steps

Prioritized list of testing improvements after the initial suite is in place.
