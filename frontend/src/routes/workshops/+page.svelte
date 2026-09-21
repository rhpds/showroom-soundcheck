<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { listWorkshops } from '$lib/api';
	import type { WorkshopListResponse, WorkshopStatus } from '$lib/types';
	import { createCheckStatusManager } from '$lib/checkStatuses.svelte';
	import {
		getTimeRange,
		extractEnvironment,
		buildWorkshopSummary,
		WORKSHOP_SIZE_MIN,
		WORKSHOP_SIZE_MAX,
		type ProvisionTypeFilter,
		type TimeWindowFilter,
		type EnvironmentType
	} from '$lib/utils';
	import WorkshopTimeline from '$lib/components/WorkshopTimeline.svelte';
	import WorkshopSummaryCards from '$lib/components/WorkshopSummaryCards.svelte';
	import WorkshopFilterBar from '$lib/components/WorkshopFilterBar.svelte';

	let { data: pageData } = $props();

	const emptyWorkshops: WorkshopListResponse = {
		items: [],
		multi_workshops: [],
		summary: {
			total: 0,
			scheduled: 0,
			provisioning: 0,
			running: 0,
			stopped: 0,
			degraded: 0,
			failed: 0,
			completed: 0
		},
		cluster_errors: [],
		fetched_at: ''
	};

	let refreshedData = $state.raw<WorkshopListResponse | null>(pageData.initialWorkshops);
	let data = $derived(refreshedData ?? emptyWorkshops);
	let clusters = $derived(pageData.clusters);
	let initialLoading = $state(!pageData.initialWorkshops);
	let refreshing = $state(false);
	let error = $state('');
	let workshopAbort: AbortController | null = null;

	// Track which MultiWorkshops are expanded
	let expandedMultiWorkshops = $state(new Set<string>());

	function toggleMultiWorkshop(name: string) {
		const next = new Set(expandedMultiWorkshops);
		if (next.has(name)) {
			next.delete(name);
		} else {
			next.add(name);
		}
		expandedMultiWorkshops = next;
	}

	let selectedClusters = $state<string[]>(pageData.filters.selectedClusters);
	let whiteGlove = $state(pageData.filters.whiteGlove);
	let multiAssetOnly = $state(pageData.filters.multiAssetOnly ?? false);
	let provisionType = $state<ProvisionTypeFilter>(pageData.filters.provisionType);
	let selectedEnvironments = $state<EnvironmentType[]>(pageData.filters.selectedEnvironments ?? []);
	let selectedStatuses = $state<WorkshopStatus[]>(pageData.filters.selectedStatuses);
	let hasFailures = $state(pageData.filters.hasFailures);
	let timeWindow = $state<TimeWindowFilter>(pageData.filters.timeWindow);
	let minSize = $state(pageData.filters.minSize);
	let maxSize = $state(pageData.filters.maxSize);
	let search = $state(pageData.filters.search ?? '');

	// `$state()` only captures its initial value. SvelteKit reuses this same
	// component instance across same-route navigations (e.g. clicking the
	// "Workshops" nav link while already on /workshops with active filters),
	// which reruns `load()` and produces a fresh `pageData.filters` without
	// otherwise updating these locals. Re-sync them whenever `pageData`
	// actually changes so the filter bar never shows stale selections.
	$effect(() => {
		const f = pageData.filters;
		selectedClusters = f.selectedClusters;
		whiteGlove = f.whiteGlove;
		multiAssetOnly = f.multiAssetOnly ?? false;
		provisionType = f.provisionType;
		selectedEnvironments = f.selectedEnvironments ?? [];
		selectedStatuses = f.selectedStatuses;
		hasFailures = f.hasFailures;
		timeWindow = f.timeWindow;
		minSize = f.minSize;
		maxSize = f.maxSize;
		search = f.search ?? '';
	});

	function matchesEnvironment(name: string): boolean {
		if (selectedEnvironments.length === 0) return true;
		const env = extractEnvironment(name);
		return env !== null && selectedEnvironments.includes(env);
	}

	function matchesSize(usersTotal: number): boolean {
		if (usersTotal < minSize) return false;
		if (maxSize < WORKSHOP_SIZE_MAX && usersTotal > maxSize) return false;
		return true;
	}

	let filteredItems = $derived(
		data.items.filter((w) => matchesEnvironment(w.name) && matchesSize(w.users_total))
	);

	let filteredMultiWorkshops = $derived(
		(data.multi_workshops ?? []).filter((mw) =>
			mw.children.some((child) => matchesEnvironment(child.name) && matchesSize(child.users_total))
		)
	);

	let hasContent = $derived(filteredItems.length > 0 || filteredMultiWorkshops.length > 0);

	// The server's `data.summary` only accounts for filters sent to the API
	// (cluster, status, white_glove, provision_type, has_failures, time
	// window, search). Environment, size range, and "multi-asset only" are
	// applied purely client-side, so once any of those narrow what's
	// rendered, `data.summary` goes stale relative to what's on screen.
	// Recompute the summary from the same items actually being displayed so
	// the counters always match the timeline below.
	let displayedSummary = $derived(
		buildWorkshopSummary([
			...(multiAssetOnly ? [] : filteredItems),
			...(data.multi_workshops ?? []).flatMap((mw) =>
				mw.children.filter(
					(child) => matchesEnvironment(child.name) && matchesSize(child.users_total)
				)
			)
		])
	);

	let hasActiveFilters = $derived(
		selectedClusters.length > 0 ||
			whiteGlove ||
			provisionType !== 'all' ||
			selectedEnvironments.length > 0 ||
			selectedStatuses.length > 0 ||
			hasFailures ||
			timeWindow !== 'all' ||
			minSize > WORKSHOP_SIZE_MIN ||
			maxSize < WORKSHOP_SIZE_MAX ||
			search !== ''
	);

	function clearAllFilters() {
		selectedClusters = [];
		whiteGlove = false;
		provisionType = 'all';
		selectedEnvironments = [];
		selectedStatuses = [];
		hasFailures = false;
		timeWindow = 'all';
		minSize = WORKSHOP_SIZE_MIN;
		maxSize = WORKSHOP_SIZE_MAX;
		search = '';
		handleFilterChange();
	}

	async function loadData(opts: { showSkeleton?: boolean } = {}) {
		workshopAbort?.abort();
		workshopAbort = new AbortController();
		const signal = workshopAbort.signal;
		if (opts.showSkeleton) {
			initialLoading = true;
		} else {
			refreshing = true;
		}
		error = '';
		try {
			const timeRange = getTimeRange(timeWindow);
			refreshedData = await listWorkshops(
				{
					cluster: selectedClusters.length > 0 ? selectedClusters : undefined,
					status: selectedStatuses.length > 0 ? selectedStatuses : undefined,
					white_glove: whiteGlove ? 'true' : undefined,
					provision_type: provisionType !== 'all' ? provisionType : undefined,
					has_failures: hasFailures || undefined,
					search: search || undefined,
					limit: 500,
					...timeRange
				},
				{ signal }
			);
		} catch (e: unknown) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			error = e instanceof Error ? e.message : 'Failed to load workshops';
		}
		initialLoading = false;
		refreshing = false;
		checks.load();
	}

	function syncFiltersToUrl() {
		const params = new URLSearchParams();
		for (const c of selectedClusters) params.append('cluster', c);
		if (whiteGlove) params.set('white_glove', 'true');
		if (multiAssetOnly) params.set('multi_asset', 'true');
		if (provisionType !== 'all') params.set('provision_type', provisionType);
		for (const e of selectedEnvironments) params.append('environment', e);
		for (const s of selectedStatuses) params.append('status', s);
		if (hasFailures) params.set('has_failures', 'true');
		if (minSize > WORKSHOP_SIZE_MIN) params.set('size_min', String(minSize));
		if (maxSize < WORKSHOP_SIZE_MAX) params.set('size_max', String(maxSize));
		if (search) params.set('search', search);
		params.set('time', timeWindow);
		const qs = params.toString();
		replaceState(`${page.url.pathname}${qs ? `?${qs}` : ''}`, {});
	}

	function handleFilterChange() {
		syncFiltersToUrl();
		loadData();
	}

	function formatFetchedAt(iso: string): string {
		if (!iso) return '';
		try {
			return new Date(iso).toLocaleTimeString(undefined, {
				hour: '2-digit',
				minute: '2-digit',
				second: '2-digit'
			});
		} catch {
			return '';
		}
	}

	// ---------------------------------------------------------------------------
	// Check status management
	// ---------------------------------------------------------------------------

	const checks = createCheckStatusManager(() => {
		const ids = new Set<string>();
		for (const ws of data.items) {
			if (ws.workshop_id) ids.add(ws.workshop_id);
		}
		for (const mws of data.multi_workshops ?? []) {
			for (const child of mws.children) {
				if (child.workshop_id) ids.add(child.workshop_id);
			}
		}
		return [...ids];
	});

	let checkStatuses = $derived(checks.statuses);

	async function runCheck(workshopId: string, cluster: string, displayName: string) {
		const err = await checks.run(workshopId, cluster, displayName);
		if (err) error = err;
	}

	onMount(() => {
		if (!pageData.initialWorkshops) {
			loadData({ showSkeleton: true });
		} else {
			checks.load();
		}
		const refreshInterval = setInterval(() => {
			if (!error) loadData();
		}, 60000);
		return () => {
			workshopAbort?.abort();
			clearInterval(refreshInterval);
			checks.destroy();
		};
	});
</script>

<div class="page-header">
	<h1 class="pf-v6-c-title pf-m-2xl">Workshops</h1>
	<div class="page-header__actions">
		{#if data.fetched_at}
			<span class="data-freshness" title="Cluster data fetched at {data.fetched_at}">
				{formatFetchedAt(data.fetched_at)}
			</span>
		{/if}
		<button
			class="pf-v6-c-button pf-m-plain"
			aria-label="Refresh"
			title="Refresh"
			onclick={() => loadData()}
			disabled={refreshing}
		>
			<svg
				viewBox="0 0 16 16"
				width="16"
				height="16"
				fill="currentColor"
				aria-hidden="true"
				class:spin={refreshing}
			>
				<path
					d="M11.534 7h3.932a.25.25 0 0 1 .192.41l-1.966 2.36a.25.25 0 0 1-.384 0l-1.966-2.36A.25.25 0 0 1 11.534 7zm-7.068 2H.534a.25.25 0 0 1-.192-.41l1.966-2.36a.25.25 0 0 1 .384 0l1.966 2.36A.25.25 0 0 1 4.466 9zM8 3a5 5 0 0 0-4.546 2.914.5.5 0 1 1-.908-.428A6 6 0 0 1 13.938 7H12.5A5.002 5.002 0 0 0 8 3zm5.454 7.086A5 5 0 0 1 3.5 9h1.438a4.002 4.002 0 0 0 7.646.914.5.5 0 0 1 .87.172z"
				/>
			</svg>
		</button>
	</div>
</div>

<WorkshopSummaryCards summary={displayedSummary} />

<WorkshopFilterBar
	{clusters}
	bind:selectedClusters
	bind:whiteGlove
	bind:multiAssetOnly
	bind:provisionType
	bind:selectedEnvironments
	bind:selectedStatuses
	bind:hasFailures
	bind:timeWindow
	bind:minSize
	bind:maxSize
	bind:search
	onchange={handleFilterChange}
/>

<!-- Content -->
{#if initialLoading}
	<div class="timeline-skeleton">
		<div class="timeline-skeleton__bar"></div>
		<div class="timeline-skeleton__bar timeline-skeleton__bar--short"></div>
		<div class="timeline-skeleton__bar"></div>
		<div class="timeline-skeleton__bar timeline-skeleton__bar--short"></div>
	</div>
{:else if error}
	<div class="pf-v6-c-alert pf-m-danger pf-m-inline" role="alert">
		<div class="pf-v6-c-alert__icon">
			<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true">
				<path
					d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
				/>
			</svg>
		</div>
		<p class="pf-v6-c-alert__title">{error}</p>
	</div>
{:else if !hasContent}
	<div class="pf-v6-c-empty-state">
		<div class="pf-v6-c-empty-state__content">
			<h2 class="pf-v6-c-empty-state__title-text">No workshops found</h2>
			<div class="pf-v6-c-empty-state__body">
				{#if hasActiveFilters}
					No workshops match the current filters.
				{:else}
					No workshops are currently active across configured clusters.
				{/if}
			</div>
			{#if hasActiveFilters}
				<div class="pf-v6-c-empty-state__actions">
					<button class="pf-v6-c-button pf-m-link" onclick={clearAllFilters}>
						Clear filters
					</button>
				</div>
			{/if}
		</div>
	</div>
{:else}
	{@const timeRange = getTimeRange(timeWindow)}
	<div class="timeline-wrapper" class:timeline-wrapper--refreshing={refreshing}>
		<WorkshopTimeline
			items={multiAssetOnly ? [] : filteredItems}
			multiWorkshops={filteredMultiWorkshops}
			filterFrom={timeRange.from_time}
			filterTo={timeRange.to_time}
			{timeWindow}
			{checkStatuses}
			onRunCheck={runCheck}
			{expandedMultiWorkshops}
			onToggleMultiWorkshop={toggleMultiWorkshop}
		/>
	</div>
{/if}

<style>
	.page-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--pf-t--global--spacer--md, 16px);
		flex-wrap: wrap;
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
	}

	.page-header__actions {
		display: flex;
		align-items: center;
		gap: var(--pf-t--global--spacer--sm, 8px);
	}

	.data-freshness {
		font-size: 0.72rem;
		color: var(--pf-t--global--icon--color--regular, #6a6e73);
		white-space: nowrap;
	}

	.timeline-wrapper {
		transition: opacity 0.2s;
	}

	.timeline-wrapper--refreshing {
		opacity: 0.6;
		pointer-events: none;
	}

	@keyframes spin {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}

	.spin {
		animation: spin 1s linear infinite;
	}

	.pf-v6-c-empty-state {
		padding: var(--pf-t--global--spacer--2xl, 48px);
		text-align: center;
	}

	.pf-v6-c-empty-state__title-text {
		margin-bottom: var(--pf-t--global--spacer--sm, 8px);
	}

	.pf-v6-c-empty-state__body {
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
	}

	.timeline-skeleton {
		display: flex;
		flex-direction: column;
		gap: 12px;
		padding: 32px;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: 8px;
		background: var(--pf-t--global--background--color--primary--default, #fff);
	}

	.timeline-skeleton__bar {
		height: 36px;
		border-radius: 6px;
		background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
		background-size: 200% 100%;
		animation: shimmer 1.5s infinite;
	}

	.timeline-skeleton__bar--short {
		width: 70%;
	}

	@keyframes shimmer {
		0% {
			background-position: 200% 0;
		}
		100% {
			background-position: -200% 0;
		}
	}
</style>
