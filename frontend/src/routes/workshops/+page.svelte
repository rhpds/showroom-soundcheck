<script lang="ts">
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { listWorkshops, createSession, getWorkshopCheckStatuses } from '$lib/api';
	import type { MultiWorkshopDashboardItem, WorkshopDashboardItem, WorkshopListResponse, WorkshopStatus, WorkshopCheckStatusMap } from '$lib/types';
	import {
		getTimeRange,
		workshopStatusColor,
		workshopStatusLabel,
		type ProvisionTypeFilter,
		type TimeWindowFilter,
		type ViewModeFilter
	} from '$lib/utils';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import WorkshopTimeline from '$lib/components/WorkshopTimeline.svelte';
	import WorkshopSummaryCards from '$lib/components/WorkshopSummaryCards.svelte';
	import WorkshopFilterBar from '$lib/components/WorkshopFilterBar.svelte';

	let { data: pageData } = $props();

	const emptyWorkshops: WorkshopListResponse = {
		items: [],
		multi_workshops: [],
		summary: { total: 0, scheduled: 0, provisioning: 0, running: 0, stopped: 0, degraded: 0, failed: 0, completed: 0 },
		cluster_errors: [],
		fetched_at: ''
	};

	let refreshedData = $state.raw<WorkshopListResponse | null>(pageData.initialWorkshops);
	let data = $derived(refreshedData ?? emptyWorkshops);
	let clusters = $derived(pageData.clusters);
	let initialLoading = $state(!pageData.initialWorkshops);
	let refreshing = $state(false);
	let error = $state('');

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

	// Unified display list: interleave multi-workshops and standalone items by date
	type DisplayRow =
		| { kind: 'workshop'; item: WorkshopDashboardItem }
		| { kind: 'multi'; item: MultiWorkshopDashboardItem }
		| { kind: 'child'; item: WorkshopDashboardItem; parentName: string };

	let displayRows = $derived.by(() => {
		const rows: DisplayRow[] = [];
		const standaloneWithDates = multiAssetOnly ? [] : data.items.map((ws) => ({
			kind: 'workshop' as const,
			item: ws,
			sortDate: ws.lifespan_start || ''
		}));
		const multiWithDates = (data.multi_workshops ?? []).map((mws) => ({
			kind: 'multi' as const,
			item: mws,
			sortDate: mws.start_date || ''
		}));

		const combined = [...standaloneWithDates, ...multiWithDates];
		combined.sort((a, b) => (b.sortDate > a.sortDate ? 1 : b.sortDate < a.sortDate ? -1 : 0));

		for (const entry of combined) {
			if (entry.kind === 'multi') {
				rows.push({ kind: 'multi', item: entry.item });
				if (expandedMultiWorkshops.has(entry.item.name)) {
					for (const child of entry.item.children) {
						rows.push({ kind: 'child', item: child, parentName: entry.item.name });
					}
				}
			} else {
				rows.push({ kind: 'workshop', item: entry.item });
			}
		}
		return rows;
	});

	let hasContent = $derived(data.items.length > 0 || (data.multi_workshops ?? []).length > 0);

	let selectedClusters = $state<string[]>(pageData.filters.selectedClusters);
	let whiteGlove = $state(pageData.filters.whiteGlove);
	let multiAssetOnly = $state(pageData.filters.multiAssetOnly ?? false);
	let provisionType = $state<ProvisionTypeFilter>(pageData.filters.provisionType);
	let selectedStatuses = $state<WorkshopStatus[]>(pageData.filters.selectedStatuses);
	let hasFailures = $state(pageData.filters.hasFailures);
	let timeWindow = $state<TimeWindowFilter>(pageData.filters.timeWindow);
	let viewMode = $state<ViewModeFilter>(pageData.filters.viewMode);

	async function loadData(opts: { showSkeleton?: boolean } = {}) {
		if (opts.showSkeleton) {
			initialLoading = true;
		} else {
			refreshing = true;
		}
		error = '';
		try {
			const timeRange = getTimeRange(timeWindow);
			refreshedData = await listWorkshops({
				cluster: selectedClusters.length > 0 ? selectedClusters : undefined,
				status: selectedStatuses.length > 0 ? selectedStatuses : undefined,
				white_glove: whiteGlove ? 'true' : undefined,
				provision_type: provisionType !== 'all' ? provisionType : undefined,
				has_failures: hasFailures || undefined,
				...timeRange
			});
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load workshops';
		}
		initialLoading = false;
		refreshing = false;
		loadCheckStatuses();
	}

	function syncFiltersToUrl() {
		const params = new URLSearchParams();
		for (const c of selectedClusters) params.append('cluster', c);
		if (whiteGlove) params.set('white_glove', 'true');
		if (multiAssetOnly) params.set('multi_asset', 'true');
		if (provisionType !== 'all') params.set('provision_type', provisionType);
		for (const s of selectedStatuses) params.append('status', s);
		if (hasFailures) params.set('has_failures', 'true');
		if (timeWindow !== 'all') params.set('time', timeWindow);
		if (viewMode !== 'table') params.set('view', viewMode);
		const qs = params.toString();
		replaceState(`${page.url.pathname}${qs ? `?${qs}` : ''}`, {});
	}

	function handleFilterChange() {
		syncFiltersToUrl();
		loadData();
	}

	function formatDate(iso: string): string {
		if (!iso) return '—';
		try {
			return new Date(iso).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return iso;
		}
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

	function provisionProgress(item: WorkshopDashboardItem): string {
		if (item.provision_ordered === 0) return '—';
		return `${item.provision_active}/${item.provision_ordered}`;
	}

	function userProgress(item: WorkshopDashboardItem): string {
		if (item.users_total === 0) return '—';
		return `${item.users_assigned}/${item.users_total}`;
	}

	// ---------------------------------------------------------------------------
	// Check status state
	// ---------------------------------------------------------------------------

	let checkStatuses = $state<WorkshopCheckStatusMap>({});
	let checkRunning = $state(new Set<string>());
	let checkPollTimer: ReturnType<typeof setInterval> | null = null;

	function allWorkshopIds(): string[] {
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
	}

	async function loadCheckStatuses() {
		const ids = allWorkshopIds();
		if (ids.length === 0) return;
		try {
			checkStatuses = await getWorkshopCheckStatuses(ids);
		} catch {
			// non-critical -- don't block the page
		}

		const hasInFlight = checkRunning.size > 0 ||
			Object.values(checkStatuses).some((s) => s && (s.status === 'running' || s.status === 'pending'));
		if (hasInFlight && !checkPollTimer) {
			checkPollTimer = setInterval(loadCheckStatuses, 10000);
		} else if (!hasInFlight && checkPollTimer) {
			clearInterval(checkPollTimer);
			checkPollTimer = null;
		}
	}

	async function runCheck(workshopId: string, cluster: string, displayName: string) {
		if (!workshopId || checkRunning.has(workshopId)) return;
		const next = new Set(checkRunning);
		next.add(workshopId);
		checkRunning = next;

		try {
			const result = await createSession({
				workshop_guids: [workshopId],
				babylon_cluster: cluster,
				name: displayName
			});
			checkStatuses = {
				...checkStatuses,
				[workshopId]: { status: 'pending', session_id: result.session_id, created_at: new Date().toISOString() }
			};
		} catch {
			// remove from running set on failure
		}

		const done = new Set(checkRunning);
		done.delete(workshopId);
		checkRunning = done;

		if (!checkPollTimer) {
			checkPollTimer = setInterval(loadCheckStatuses, 10000);
		}
	}

	function checkStatusColor(status: string): string {
		switch (status) {
			case 'completed': return 'green';
			case 'running': case 'pending': return 'blue';
			case 'failed': return 'red';
			default: return 'grey';
		}
	}

	function checkStatusLabel(status: string): string {
		switch (status) {
			case 'completed': return 'Passed';
			case 'running': return 'Running';
			case 'pending': return 'Pending';
			case 'failed': return 'Failed';
			default: return status;
		}
	}

	onMount(() => {
		if (!pageData.initialWorkshops) {
			loadData({ showSkeleton: true });
		} else {
			loadCheckStatuses();
		}
		const refreshInterval = setInterval(() => {
			if (!error) loadData();
		}, 60000);
		return () => {
			clearInterval(refreshInterval);
			if (checkPollTimer) clearInterval(checkPollTimer);
		};
	});
</script>

<div class="page-header">
	<h1 class="pf-v6-c-title pf-m-2xl">Workshops</h1>
	<div class="page-header__actions">
		<div class="view-toggle">
			<button
				class="pf-v6-c-button"
				class:pf-m-primary={viewMode === 'table'}
				class:pf-m-secondary={viewMode !== 'table'}
				onclick={() => { viewMode = 'table'; syncFiltersToUrl(); }}
				aria-label="Table view"
			>
				<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
					<path d="M1 2h14v2H1zm0 4h14v2H1zm0 4h14v2H1zm0 4h14v2H1z" />
				</svg>
			</button>
			<button
				class="pf-v6-c-button"
				class:pf-m-primary={viewMode === 'timeline'}
				class:pf-m-secondary={viewMode !== 'timeline'}
				onclick={() => { viewMode = 'timeline'; syncFiltersToUrl(); }}
				aria-label="Timeline view"
			>
				<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
					<path d="M1 3h4v2H1zm6 0h6v2H7zM1 7h8v2H1zm10 0h4v2H11zM1 11h5v2H1zm7 0h7v2H8z" />
				</svg>
			</button>
		</div>
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
			<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true" class:spin={refreshing}>
				<path
					d="M11.534 7h3.932a.25.25 0 0 1 .192.41l-1.966 2.36a.25.25 0 0 1-.384 0l-1.966-2.36A.25.25 0 0 1 11.534 7zm-7.068 2H.534a.25.25 0 0 1-.192-.41l1.966-2.36a.25.25 0 0 1 .384 0l1.966 2.36A.25.25 0 0 1 4.466 9zM8 3a5 5 0 0 0-4.546 2.914.5.5 0 1 1-.908-.428A6 6 0 0 1 13.938 7H12.5A5.002 5.002 0 0 0 8 3zm5.454 7.086A5 5 0 0 1 3.5 9h1.438a4.002 4.002 0 0 0 7.646.914.5.5 0 0 1 .87.172z"
				/>
			</svg>
		</button>
	</div>
</div>

<WorkshopSummaryCards summary={data.summary} />

<WorkshopFilterBar
	{clusters}
	bind:selectedClusters
	bind:whiteGlove
	bind:multiAssetOnly
	bind:provisionType
	bind:selectedStatuses
	bind:hasFailures
	bind:timeWindow
	onchange={handleFilterChange}
/>

<!-- Content -->
{#if initialLoading}
	<TableSkeleton
		headers={['Status', 'Name', 'Cluster', 'Catalog Item', 'Provisioning', 'Users', 'Flags', 'Check', 'Start', 'End']}
		showPin={false}
		showActions={false}
	/>
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
				{#if selectedClusters.length > 0 || whiteGlove || provisionType !== 'all' || selectedStatuses.length > 0 || hasFailures || timeWindow !== 'all'}
					No workshops match the current filters.
				{:else}
					No workshops are currently active across configured clusters.
				{/if}
			</div>
			{#if selectedClusters.length > 0 || whiteGlove || provisionType !== 'all' || selectedStatuses.length > 0 || hasFailures || timeWindow !== 'all'}
				<div class="pf-v6-c-empty-state__actions">
					<button class="pf-v6-c-button pf-m-link" onclick={() => { selectedClusters = []; whiteGlove = false; provisionType = 'all'; selectedStatuses = []; hasFailures = false; timeWindow = 'all'; handleFilterChange(); }}>
						Clear filters
					</button>
				</div>
			{/if}
		</div>
	</div>
{:else if viewMode === 'table'}
	<div class="table-wrapper" class:table-wrapper--refreshing={refreshing}>
		<table class="pf-v6-c-table pf-m-grid-md" role="grid">
			<thead class="pf-v6-c-table__thead">
				<tr class="pf-v6-c-table__tr">
					<th class="pf-v6-c-table__th col-expand"></th>
					<th class="pf-v6-c-table__th">Status</th>
					<th class="pf-v6-c-table__th">Name</th>
					<th class="pf-v6-c-table__th">Cluster</th>
					<th class="pf-v6-c-table__th">Catalog Item</th>
					<th class="pf-v6-c-table__th">Provisioning</th>
					<th class="pf-v6-c-table__th">Users</th>
					<th class="pf-v6-c-table__th col-flags">Flags</th>
					<th class="pf-v6-c-table__th col-check">Check</th>
					<th class="pf-v6-c-table__th">Start</th>
					<th class="pf-v6-c-table__th">End</th>
				</tr>
			</thead>
			<tbody class="pf-v6-c-table__tbody">
				{#each displayRows as row}
					{#if row.kind === 'multi'}
						{@const mws = row.item}
						{@const isExpanded = expandedMultiWorkshops.has(mws.name)}
						<tr class="pf-v6-c-table__tr mws-row" class:mws-row--expanded={isExpanded}>
							<td class="pf-v6-c-table__td col-expand">
								<button
									class="expand-toggle"
									class:expand-toggle--open={isExpanded}
									onclick={() => toggleMultiWorkshop(mws.name)}
									aria-label={isExpanded ? 'Collapse' : 'Expand'}
									title="{mws.children.length} workshops"
								>
									<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true">
										<path d="M6 3l5 5-5 5V3z" />
									</svg>
								</button>
							</td>
							<td class="pf-v6-c-table__td" data-label="Status">
								<span class="ws-status-badge ws-status-badge--{workshopStatusColor(mws.status)}">
									{workshopStatusLabel(mws.status)}
								</span>
							</td>
							<td class="pf-v6-c-table__td" data-label="Name">
								<div class="ws-name-cell">
									{#if mws.catalog_url}
										<a
											href={mws.catalog_url}
											class="ws-display-name ws-link mws-display-name"
											target="_blank"
											rel="noopener noreferrer"
										>
											{mws.display_name}
											<svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor" aria-hidden="true">
												<path d="M8.636 3.5a.5.5 0 0 0-.5-.5H1.5A1.5 1.5 0 0 0 0 4.5v10A1.5 1.5 0 0 0 1.5 16h10a1.5 1.5 0 0 0 1.5-1.5V7.864a.5.5 0 0 0-1 0V14.5a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-10a.5.5 0 0 1 .5-.5h6.636a.5.5 0 0 0 .5-.5z" />
												<path d="M16 .5a.5.5 0 0 0-.5-.5h-5a.5.5 0 0 0 0 1h3.793L6.146 9.146a.5.5 0 1 0 .708.708L15 1.707V5.5a.5.5 0 0 0 1 0v-5z" />
											</svg>
										</a>
									{:else}
										<span class="ws-display-name mws-display-name">{mws.display_name}</span>
									{/if}
									<span class="mws-meta">
										{mws.number_seats} seats &middot; {mws.children.length} workshops
										{#if mws.purpose}
											&middot; {mws.purpose}
										{/if}
									</span>
									{#if mws.requester}
										<span class="ws-requester">{mws.requester}</span>
									{/if}
								</div>
							</td>
							<td class="pf-v6-c-table__td" data-label="Cluster">
								<span class="cluster-badge">{mws.cluster}</span>
							</td>
							<td class="pf-v6-c-table__td" data-label="Catalog Item">
								<span class="catalog-label">{mws.assets.length} items</span>
							</td>
							<td class="pf-v6-c-table__td" data-label="Provisioning">
								<div class="provision-cell">
									<span>{mws.provision_active}/{mws.provision_ordered}</span>
									{#if mws.provision_failed > 0}
										<span class="provision-failed" title="{mws.provision_failed} failed">
											{mws.provision_failed} failed
										</span>
									{/if}
								</div>
							</td>
							<td class="pf-v6-c-table__td" data-label="Users">
								{#if mws.users_total > 0}
									{mws.users_assigned}/{mws.users_total}
								{:else}
									—
								{/if}
							</td>
							<td class="pf-v6-c-table__td col-flags" data-label="Flags">
								<span class="flag-badge flag-badge--event" title="Multi-Workshop Event">EVENT</span>
							</td>
							<td class="pf-v6-c-table__td col-check" data-label="Check">
								<span class="flag-none">—</span>
							</td>
							<td class="pf-v6-c-table__td" data-label="Start">
								{formatDate(mws.start_date)}
							</td>
							<td class="pf-v6-c-table__td" data-label="End">
								{formatDate(mws.end_date)}
							</td>
						</tr>
					{:else}
						{@const workshop = row.item}
						{@const isChild = row.kind === 'child'}
						<tr class="pf-v6-c-table__tr" class:child-row={isChild}>
							<td class="pf-v6-c-table__td col-expand">
								{#if isChild}
									<span class="child-indent"></span>
								{/if}
							</td>
							<td class="pf-v6-c-table__td" data-label="Status">
								<span
									class="ws-status-badge ws-status-badge--{workshopStatusColor(workshop.status)}"
								>
									{workshopStatusLabel(workshop.status)}
								</span>
							</td>
							<td class="pf-v6-c-table__td" data-label="Name">
								<div class="ws-name-cell">
									{#if workshop.catalog_url}
										<a
											href={workshop.catalog_url}
											class="ws-display-name ws-link"
											target="_blank"
											rel="noopener noreferrer"
										>
											{workshop.display_name}
											<svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor" aria-hidden="true">
												<path d="M8.636 3.5a.5.5 0 0 0-.5-.5H1.5A1.5 1.5 0 0 0 0 4.5v10A1.5 1.5 0 0 0 1.5 16h10a1.5 1.5 0 0 0 1.5-1.5V7.864a.5.5 0 0 0-1 0V14.5a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-10a.5.5 0 0 1 .5-.5h6.636a.5.5 0 0 0 .5-.5z" />
												<path d="M16 .5a.5.5 0 0 0-.5-.5h-5a.5.5 0 0 0 0 1h3.793L6.146 9.146a.5.5 0 1 0 .708.708L15 1.707V5.5a.5.5 0 0 0 1 0v-5z" />
											</svg>
										</a>
									{:else}
										<span class="ws-display-name">{workshop.display_name}</span>
									{/if}
									{#if !isChild && workshop.requester}
										<span class="ws-requester">{workshop.requester}</span>
									{/if}
								</div>
							</td>
							<td class="pf-v6-c-table__td" data-label="Cluster">
								<span class="cluster-badge">{workshop.cluster}</span>
							</td>
							<td class="pf-v6-c-table__td" data-label="Catalog Item">
								<span class="catalog-label">{workshop.catalog_item || '—'}</span>
							</td>
							<td class="pf-v6-c-table__td" data-label="Provisioning">
								<div class="provision-cell">
									<span>{provisionProgress(workshop)}</span>
									{#if workshop.provision_failed > 0}
										<span class="provision-failed" title="{workshop.provision_failed} failed">
											{workshop.provision_failed} failed
										</span>
									{/if}
								</div>
							</td>
							<td class="pf-v6-c-table__td" data-label="Users">
								{userProgress(workshop)}
							</td>
							<td class="pf-v6-c-table__td col-flags" data-label="Flags">
								<div class="flags-cell">
									{#if workshop.white_glove}
										<span class="flag-badge flag-badge--wg" title="White-glove">WG</span>
									{/if}
									{#if workshop.demo_team_provisioned}
										<span class="flag-badge flag-badge--dt" title="Demo team provisioned">DT</span>
									{/if}
								{#if workshop.locked}
									<span class="flag-badge flag-badge--locked" title="Locked">
										<svg viewBox="0 0 16 16" width="11" height="11" fill="currentColor" aria-hidden="true">
											<path d="M8 1a3 3 0 0 0-3 3v2H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-1V4a3 3 0 0 0-3-3zm-2 3a2 2 0 1 1 4 0v2H6V4z" />
										</svg>
									</span>
								{/if}
								{#if workshop.disable_auto_stop}
									<span class="flag-badge flag-badge--no-autostop" title="No auto-stop">
										<svg viewBox="0 0 16 16" width="11" height="11" fill="currentColor" aria-hidden="true">
											<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 1a6 6 0 1 1 0 12A6 6 0 0 1 8 2zM6 5v6h1.5V5H6zm2.5 0v6H10V5H8.5z" />
										</svg>
									</span>
								{/if}
								{#if !workshop.white_glove && !workshop.demo_team_provisioned && !workshop.locked && !workshop.disable_auto_stop}
									<span class="flag-none">—</span>
								{/if}
								</div>
							</td>
							<td class="pf-v6-c-table__td col-check" data-label="Check">
								{#if workshop.workshop_id}
									{@const cs = checkStatuses[workshop.workshop_id]}
									<div class="check-cell">
										{#if cs}
											<a
												href="/session/{cs.session_id}"
												target="_blank"
												rel="noopener noreferrer"
												class="check-badge check-badge--{checkStatusColor(cs.status)}"
												title="Last check: {checkStatusLabel(cs.status)}"
											>
												{checkStatusLabel(cs.status)}
											</a>
										{/if}
										{#if checkRunning.has(workshop.workshop_id)}
											<span class="check-badge check-badge--blue" title="Starting check...">
												<svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor" aria-hidden="true" class="spin">
													<path d="M11.534 7h3.932a.25.25 0 0 1 .192.41l-1.966 2.36a.25.25 0 0 1-.384 0l-1.966-2.36A.25.25 0 0 1 11.534 7zm-7.068 2H.534a.25.25 0 0 1-.192-.41l1.966-2.36a.25.25 0 0 1 .384 0l1.966 2.36A.25.25 0 0 1 4.466 9z" />
												</svg>
											</span>
										{:else}
											<button
												class="check-run-btn"
												title="Run showroom check"
												onclick={() => runCheck(workshop.workshop_id, workshop.cluster, workshop.display_name)}
											>
												<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true">
													<path d="M4 2l10 6-10 6V2z" />
												</svg>
											</button>
										{/if}
									</div>
								{:else}
									<span class="flag-none">—</span>
								{/if}
							</td>
							<td class="pf-v6-c-table__td" data-label="Start">
								{formatDate(workshop.lifespan_start)}
							</td>
							<td class="pf-v6-c-table__td" data-label="End">
								{formatDate(workshop.lifespan_end)}
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	{@const timeRange = getTimeRange(timeWindow)}
	<div class="table-wrapper" class:table-wrapper--refreshing={refreshing}>
		<WorkshopTimeline items={multiAssetOnly ? [] : data.items} multiWorkshops={data.multi_workshops ?? []} filterFrom={timeRange.from_time} filterTo={timeRange.to_time} {timeWindow} {checkStatuses} onRunCheck={runCheck} />
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

	.view-toggle {
		display: flex;
		gap: 2px;
	}

	.view-toggle .pf-v6-c-button {
		padding: 6px 10px;
	}

	.data-freshness {
		font-size: 0.72rem;
		color: var(--pf-t--global--icon--color--regular, #6a6e73);
		white-space: nowrap;
	}

	.table-wrapper {
		transition: opacity 0.2s;
	}

	.table-wrapper--refreshing {
		opacity: 0.6;
		pointer-events: none;
	}

	@keyframes spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}

	.spin {
		animation: spin 1s linear infinite;
	}

	/* Workshop status badges */
	.ws-status-badge {
		display: inline-block;
		padding: 2px 8px;
		border-radius: 12px;
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.03em;
		white-space: nowrap;
	}

	.ws-status-badge--green {
		color: #1e4620;
		background: #e7f5e8;
		border: 1px solid #6ec071;
	}
	.ws-status-badge--blue {
		color: #003d73;
		background: #e7f1fa;
		border: 1px solid #73bcf7;
	}
	.ws-status-badge--gold {
		color: #6b4400;
		background: #fef6e6;
		border: 1px solid #f0c75e;
	}
	.ws-status-badge--orange {
		color: #6e3101;
		background: #fef3e8;
		border: 1px solid #f4a460;
	}
	.ws-status-badge--red {
		color: #7d1007;
		background: #fce8e6;
		border: 1px solid #e87a72;
	}
	.ws-status-badge--grey {
		color: #4a4a4a;
		background: #f0f0f0;
		border: 1px solid #d2d2d2;
	}

	/* Table cells */
	.ws-name-cell {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.ws-display-name {
		font-weight: 500;
	}

	.ws-link {
		color: var(--pf-t--global--color--link--default, #0066cc);
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}

	.ws-link:hover {
		text-decoration: underline;
	}

	.ws-requester {
		font-size: 0.75rem;
		opacity: 0.6;
	}

	.cluster-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 4px;
		font-size: 0.7rem;
		font-weight: 500;
		background: #e7f1fa;
		color: #003d73;
		border: 1px solid #73bcf7;
	}

	.catalog-label {
		font-size: 0.8rem;
		opacity: 0.8;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 180px;
		display: inline-block;
	}

	.provision-cell {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.provision-failed {
		font-size: 0.7rem;
		color: #c9190b;
		font-weight: 500;
	}

	.col-flags {
		width: 70px;
	}

	.flags-cell {
		display: flex;
		gap: 4px;
		align-items: center;
	}

	.flag-badge {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		padding: 1px 5px;
		border-radius: 4px;
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: uppercase;
	}

	.flag-badge--wg {
		background: #fef6e6;
		color: #6b4400;
		border: 1px solid #f0c75e;
	}

	.flag-badge--dt {
		background: #f3e8fd;
		color: #4a148c;
		border: 1px solid #b388ff;
	}

	.flag-badge--locked {
		background: #e7f1fa;
		color: #003d73;
		border: 1px solid #73bcf7;
	}

	.flag-badge--no-autostop {
		background: #fef3e8;
		color: #6e3101;
		border: 1px solid #f4a460;
	}

	.flag-none {
		opacity: 0.3;
	}

	/* Empty state */
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

	/* Multi-Workshop rows */
	.col-expand {
		width: 32px;
		padding-right: 0 !important;
	}

	.expand-toggle {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		border: none;
		background: none;
		cursor: pointer;
		border-radius: 4px;
		transition: transform 0.15s, background 0.15s;
		color: var(--pf-t--global--icon--color--regular, #6a6e73);
	}

	.expand-toggle:hover {
		background: var(--pf-t--global--background--color--secondary--default, #f5f5f5);
	}

	.expand-toggle--open {
		transform: rotate(90deg);
	}

	.mws-row {
		background: var(--pf-t--global--background--color--secondary--default, #f9f9f9);
		border-left: 3px solid var(--pf-t--global--color--brand--default, #0066cc);
	}

	.mws-row--expanded {
		border-bottom-color: transparent;
	}

	.mws-display-name {
		font-size: 1rem;
	}

	.mws-meta {
		font-size: 0.72rem;
		opacity: 0.65;
	}

	.child-row {
		background: var(--pf-t--global--background--color--primary--default, #fff);
		border-left: 3px solid #e0e0e0;
	}

	.child-indent {
		display: inline-block;
		width: 12px;
		height: 12px;
		border-left: 2px solid #ccc;
		border-bottom: 2px solid #ccc;
		margin-left: 4px;
		margin-bottom: -4px;
	}

	.flag-badge--event {
		background: #e7f1fa;
		color: #003d73;
		border: 1px solid #73bcf7;
	}

	/* Check column */
	.col-check {
		width: 110px;
	}

	.check-cell {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.check-badge {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 10px;
		font-size: 0.65rem;
		font-weight: 600;
		text-transform: uppercase;
		text-decoration: none;
		white-space: nowrap;
	}

	.check-badge--green {
		color: #1e4620;
		background: #e7f5e8;
		border: 1px solid #6ec071;
	}

	.check-badge--blue {
		color: #003d73;
		background: #e7f1fa;
		border: 1px solid #73bcf7;
	}

	.check-badge--red {
		color: #7d1007;
		background: #fce8e6;
		border: 1px solid #e87a72;
	}

	.check-badge--grey {
		color: #4a4a4a;
		background: #f0f0f0;
		border: 1px solid #d2d2d2;
	}

	.check-run-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		border: 1px solid #d2d2d2;
		background: none;
		cursor: pointer;
		border-radius: 4px;
		color: var(--pf-t--global--icon--color--regular, #6a6e73);
		transition: background 0.15s, color 0.15s;
		flex-shrink: 0;
	}

	.check-run-btn:hover {
		background: var(--pf-t--global--background--color--secondary--default, #f5f5f5);
		color: var(--pf-t--global--color--brand--default, #0066cc);
		border-color: var(--pf-t--global--color--brand--default, #0066cc);
	}
</style>
