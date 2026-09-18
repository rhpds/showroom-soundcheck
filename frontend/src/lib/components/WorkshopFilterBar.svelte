<script lang="ts">
	import { untrack } from 'svelte';
	import type { WorkshopStatus } from '$lib/types';
	import type { ProvisionTypeFilter, TimeWindowFilter, EnvironmentType } from '$lib/utils';
	import {
		workshopStatusLabel,
		ALL_WORKSHOP_STATUSES,
		ENVIRONMENT_VALUES,
		environmentLabel,
		WORKSHOP_SIZE_STEPS,
		WORKSHOP_SIZE_MIN,
		WORKSHOP_SIZE_MAX
	} from '$lib/utils';
	import RangeSlider from './RangeSlider.svelte';

	let {
		clusters,
		selectedClusters = $bindable([]),
		whiteGlove = $bindable(false),
		multiAssetOnly = $bindable(false),
		provisionType = $bindable('all' as ProvisionTypeFilter),
		selectedEnvironments = $bindable([] as EnvironmentType[]),
		selectedStatuses = $bindable([] as WorkshopStatus[]),
		hasFailures = $bindable(false),
		timeWindow = $bindable('all' as TimeWindowFilter),
		minSize = $bindable(WORKSHOP_SIZE_MIN),
		maxSize = $bindable(WORKSHOP_SIZE_MAX),
		search = $bindable(''),
		onchange
	}: {
		clusters: string[];
		selectedClusters: string[];
		whiteGlove: boolean;
		multiAssetOnly: boolean;
		provisionType: ProvisionTypeFilter;
		selectedEnvironments: EnvironmentType[];
		selectedStatuses: WorkshopStatus[];
		hasFailures: boolean;
		timeWindow: TimeWindowFilter;
		minSize: number;
		maxSize: number;
		search: string;
		onchange: () => void;
	} = $props();

	// Whether the secondary "More filters" row is expanded. Seeded once from
	// whether any secondary filter *other than Environment* is already active
	// (e.g. a deep link like `?cluster=...`), so such links land expanded.
	// After that, this is purely toggled by the "More filters" button — it is
	// intentionally NOT re-derived from filter state, so the row can always be
	// manually collapsed even while filters inside it remain active.
	let showSecondary = $state(
		untrack(
			() =>
				whiteGlove ||
				multiAssetOnly ||
				provisionType !== 'all' ||
				hasFailures ||
				selectedClusters.length > 0 ||
				minSize > WORKSHOP_SIZE_MIN ||
				maxSize < WORKSHOP_SIZE_MAX
		)
	);

	// Local, uncommitted search text — recomputed from `search` whenever it
	// changes externally (e.g. "Clear all", removing the search pill, or a
	// browser back/forward navigation), but overridable while typing without
	// committing on every keystroke.
	let searchInput = $derived(search);

	function commitSearch() {
		if (search === searchInput) return;
		search = searchInput;
		onchange();
	}

	function clearSearch() {
		search = '';
		searchInput = '';
		onchange();
	}

	function toggleCluster(cluster: string) {
		if (selectedClusters.includes(cluster)) {
			selectedClusters = selectedClusters.filter((c) => c !== cluster);
		} else {
			selectedClusters = [...selectedClusters, cluster];
		}
		onchange();
	}

	function toggleStatus(status: WorkshopStatus) {
		if (selectedStatuses.includes(status)) {
			selectedStatuses = selectedStatuses.filter((s) => s !== status);
		} else {
			selectedStatuses = [...selectedStatuses, status];
		}
		onchange();
	}

	function toggleEnvironment(env: EnvironmentType) {
		if (selectedEnvironments.includes(env)) {
			selectedEnvironments = selectedEnvironments.filter((e) => e !== env);
		} else {
			selectedEnvironments = [...selectedEnvironments, env];
		}
		onchange();
	}

	function clearFilters() {
		selectedClusters = [];
		whiteGlove = false;
		multiAssetOnly = false;
		provisionType = 'all';
		selectedEnvironments = [];
		selectedStatuses = [];
		hasFailures = false;
		timeWindow = 'all';
		minSize = WORKSHOP_SIZE_MIN;
		maxSize = WORKSHOP_SIZE_MAX;
		search = '';
		searchInput = '';
		onchange();
	}

	let sizeFilterActive = $derived(minSize > WORKSHOP_SIZE_MIN || maxSize < WORKSHOP_SIZE_MAX);

	let hasActiveFilters = $derived(
		selectedClusters.length > 0 ||
			whiteGlove ||
			multiAssetOnly ||
			provisionType !== 'all' ||
			selectedEnvironments.length > 0 ||
			selectedStatuses.length > 0 ||
			hasFailures ||
			timeWindow !== 'all' ||
			sizeFilterActive ||
			search !== ''
	);

	// Count of active filters that live in the secondary "More filters" row,
	// shown as a badge on the toggle button. This is independent of whether
	// the row is currently expanded (see `showSecondary`).
	let secondaryFilterCount = $derived(
		(whiteGlove ? 1 : 0) +
			(multiAssetOnly ? 1 : 0) +
			(hasFailures ? 1 : 0) +
			(provisionType !== 'all' ? 1 : 0) +
			(sizeFilterActive ? 1 : 0) +
			selectedClusters.length +
			selectedEnvironments.length
	);

	type ActivePill = { key: string; label: string; clear: () => void };

	let activePills = $derived.by(() => {
		const pills: ActivePill[] = [];
		if (search) {
			pills.push({
				key: 'search',
				label: `Search: "${search}"`,
				clear: () => {
					clearSearch();
				}
			});
		}
		for (const c of selectedClusters) {
			pills.push({
				key: `cluster-${c}`,
				label: `Cluster: ${c}`,
				clear: () => {
					selectedClusters = selectedClusters.filter((x) => x !== c);
					onchange();
				}
			});
		}
		if (timeWindow !== 'all') {
			const labels: Record<string, string> = {
				today: 'Today',
				'24h': 'Next 24h',
				week: 'This week'
			};
			pills.push({
				key: 'time',
				label: `Time: ${labels[timeWindow] ?? timeWindow}`,
				clear: () => {
					timeWindow = 'all';
					onchange();
				}
			});
		}
		for (const s of selectedStatuses) {
			pills.push({
				key: `status-${s}`,
				label: `Status: ${s.charAt(0).toUpperCase() + s.slice(1)}`,
				clear: () => {
					selectedStatuses = selectedStatuses.filter((x) => x !== s);
					onchange();
				}
			});
		}
		if (whiteGlove) {
			pills.push({
				key: 'wg',
				label: 'White-glove',
				clear: () => {
					whiteGlove = false;
					onchange();
				}
			});
		}
		if (multiAssetOnly) {
			pills.push({
				key: 'multi',
				label: 'Multi-asset',
				clear: () => {
					multiAssetOnly = false;
					onchange();
				}
			});
		}
		if (hasFailures) {
			pills.push({
				key: 'failures',
				label: 'Has failures',
				clear: () => {
					hasFailures = false;
					onchange();
				}
			});
		}
		if (provisionType !== 'all') {
			const labels: Record<string, string> = {
				self_service: 'Self-service',
				demo_team: 'Demo team'
			};
			pills.push({
				key: 'provision',
				label: `Provisioned by: ${labels[provisionType] ?? provisionType}`,
				clear: () => {
					provisionType = 'all';
					onchange();
				}
			});
		}
		for (const env of selectedEnvironments) {
			pills.push({
				key: `env-${env}`,
				label: `Env: ${environmentLabel(env)}`,
				clear: () => {
					selectedEnvironments = selectedEnvironments.filter((e) => e !== env);
					onchange();
				}
			});
		}
		if (sizeFilterActive) {
			const minActive = minSize > WORKSHOP_SIZE_MIN;
			const maxActive = maxSize < WORKSHOP_SIZE_MAX;
			const maxLabel = maxSize >= WORKSHOP_SIZE_MAX ? `${maxSize}+` : `${maxSize}`;
			let label: string;
			if (minActive && maxActive) {
				label = `Size: ${minSize}\u2013${maxLabel} users`;
			} else if (minActive) {
				label = `Size: ${minSize}+ users`;
			} else {
				label = `Size: \u2264${maxLabel} users`;
			}
			pills.push({
				key: 'size',
				label,
				clear: () => {
					minSize = WORKSHOP_SIZE_MIN;
					maxSize = WORKSHOP_SIZE_MAX;
					onchange();
				}
			});
		}
		return pills;
	});
</script>

<div class="filter-bar" role="toolbar" aria-label="Workshop filters">
	<!-- Primary filters row -->
	<div class="filter-row filter-row--primary">
		<div class="filter-group">
			<span class="filter-label">Search</span>
			<input
				type="search"
				class="search-input"
				placeholder="Name, email, namespace..."
				aria-label="Search workshops"
				bind:value={searchInput}
				onkeydown={(e) => {
					if (e.key === 'Enter') commitSearch();
				}}
				onblur={commitSearch}
			/>
		</div>

		<div class="filter-separator"></div>
		<div class="filter-group">
			<span class="filter-label">Time</span>
			<div class="filter-chips" role="group" aria-label="Time window filter">
				<button
					class="filter-chip"
					class:active={timeWindow === 'all'}
					aria-pressed={timeWindow === 'all'}
					onclick={() => {
						timeWindow = 'all';
						onchange();
					}}>All</button
				>
				<button
					class="filter-chip"
					class:active={timeWindow === 'today'}
					aria-pressed={timeWindow === 'today'}
					onclick={() => {
						timeWindow = 'today';
						onchange();
					}}>Today</button
				>
				<button
					class="filter-chip"
					class:active={timeWindow === '24h'}
					aria-pressed={timeWindow === '24h'}
					onclick={() => {
						timeWindow = '24h';
						onchange();
					}}>Next 24h</button
				>
				<button
					class="filter-chip"
					class:active={timeWindow === 'week'}
					aria-pressed={timeWindow === 'week'}
					onclick={() => {
						timeWindow = 'week';
						onchange();
					}}>This week</button
				>
			</div>
		</div>

		<div class="filter-separator"></div>
		<div class="filter-group">
			<span class="filter-label">Status</span>
			<div class="filter-chips" role="group" aria-label="Status filter">
				{#each ALL_WORKSHOP_STATUSES as status}
					<button
						class="filter-chip"
						class:active={selectedStatuses.includes(status)}
						aria-pressed={selectedStatuses.includes(status)}
						onclick={() => toggleStatus(status)}>{workshopStatusLabel(status)}</button
					>
				{/each}
			</div>
		</div>

		<div class="filter-actions">
			<button
				class="more-filters-btn"
				class:more-filters-btn--active={showSecondary}
				onclick={() => {
					showSecondary = !showSecondary;
				}}
				aria-expanded={showSecondary}
			>
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true">
					<path
						d="M1.5 1.5A.5.5 0 0 1 2 1h12a.5.5 0 0 1 .4.8L9.667 7.933V13.5a.5.5 0 0 1-.243.429l-2.667 1.6A.5.5 0 0 1 6 15.1V7.933L1.1 1.8a.5.5 0 0 1 .4-.8z"
					/>
				</svg>
				More filters
				{#if secondaryFilterCount > 0}
					<span class="filter-count">{secondaryFilterCount}</span>
				{/if}
			</button>

			{#if hasActiveFilters}
				<button class="clear-filters-btn" onclick={clearFilters}> Clear all </button>
			{/if}
		</div>
	</div>

	<!-- Secondary filters row (collapsible) -->
	{#if showSecondary}
		<div class="filter-row filter-row--secondary">
			<div class="filter-group">
				<span class="filter-label">Environment</span>
				<div class="filter-chips" role="group" aria-label="Environment filter">
					{#each ENVIRONMENT_VALUES as env}
						<button
							class="filter-chip"
							class:active={selectedEnvironments.includes(env)}
							aria-pressed={selectedEnvironments.includes(env)}
							onclick={() => toggleEnvironment(env)}>{environmentLabel(env)}</button
						>
					{/each}
				</div>
			</div>

			<div class="filter-separator"></div>

			<div class="filter-group">
				<span class="filter-label">Flags</span>
				<div class="filter-chips" role="group" aria-label="Flag filters">
					<button
						class="filter-chip"
						class:active={whiteGlove}
						aria-pressed={whiteGlove}
						onclick={() => {
							whiteGlove = !whiteGlove;
							onchange();
						}}>White-glove</button
					>
					<button
						class="filter-chip"
						class:active={multiAssetOnly}
						aria-pressed={multiAssetOnly}
						onclick={() => {
							multiAssetOnly = !multiAssetOnly;
							onchange();
						}}>Multi-asset</button
					>
					<button
						class="filter-chip"
						class:active={hasFailures}
						aria-pressed={hasFailures}
						onclick={() => {
							hasFailures = !hasFailures;
							onchange();
						}}>Has failures</button
					>
				</div>
			</div>

			<div class="filter-separator"></div>

			<div class="filter-group">
				<span class="filter-label">Size</span>
				<RangeSlider
					steps={[...WORKSHOP_SIZE_STEPS]}
					bind:valueMin={minSize}
					bind:valueMax={maxSize}
					{onchange}
					minAriaLabel="Minimum workshop size"
					maxAriaLabel="Maximum workshop size"
				/>
			</div>

			<div class="filter-separator"></div>

			<div class="filter-group">
				<span class="filter-label">Provisioned by</span>
				<div class="filter-chips" role="group" aria-label="Provision type filter">
					<button
						class="filter-chip"
						class:active={provisionType === 'all'}
						aria-pressed={provisionType === 'all'}
						onclick={() => {
							provisionType = 'all';
							onchange();
						}}>All</button
					>
					<button
						class="filter-chip"
						class:active={provisionType === 'self_service'}
						aria-pressed={provisionType === 'self_service'}
						onclick={() => {
							provisionType = 'self_service';
							onchange();
						}}>Self-service</button
					>
					<button
						class="filter-chip"
						class:active={provisionType === 'demo_team'}
						aria-pressed={provisionType === 'demo_team'}
						onclick={() => {
							provisionType = 'demo_team';
							onchange();
						}}>Demo team</button
					>
				</div>
			</div>

			{#if clusters.length > 0}
				<div class="filter-separator"></div>

				<div class="filter-group">
					<span class="filter-label">Cluster</span>
					<div class="filter-chips" role="group" aria-label="Cluster filter">
						{#each clusters as cluster}
							<button
								class="filter-chip"
								class:active={selectedClusters.includes(cluster)}
								onclick={() => toggleCluster(cluster)}
								aria-pressed={selectedClusters.includes(cluster)}>{cluster}</button
							>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Active filter pills -->
	{#if activePills.length > 0}
		<div class="filter-pills" role="list" aria-label="Active filters">
			{#each activePills as pill (pill.key)}
				<span class="filter-pill" role="listitem">
					{pill.label}
					<button
						class="filter-pill__remove"
						onclick={pill.clear}
						aria-label="Remove {pill.label} filter"
					>
						<svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor" aria-hidden="true">
							<path
								d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z"
							/>
						</svg>
					</button>
				</span>
			{/each}
		</div>
	{/if}
</div>

<style>
	.filter-bar {
		display: flex;
		flex-direction: column;
		gap: 0;
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
		border-radius: 8px;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		background: var(--pf-t--global--background--color--secondary--default, #f5f5f5);
		overflow: hidden;
	}

	.filter-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--pf-t--global--spacer--md, 16px);
		padding: 10px 16px;
	}

	.filter-row--secondary {
		border-top: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		background: var(--pf-t--global--background--color--primary--default, #fff);
	}

	.filter-separator {
		width: 1px;
		height: 24px;
		background: var(--pf-t--global--border--color--default, #d2d2d2);
		flex-shrink: 0;
	}

	.filter-group {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.filter-label {
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		opacity: 0.55;
		white-space: nowrap;
	}

	.filter-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}

	.filter-chip {
		padding: 3px 10px;
		border-radius: 14px;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		background: var(--pf-t--global--background--color--primary--default, #fff);
		font-size: 0.75rem;
		cursor: pointer;
		transition:
			background 0.15s,
			border-color 0.15s,
			color 0.15s;
		color: inherit;
	}

	.filter-chip:hover {
		border-color: var(--pf-t--global--color--brand--default, #0066cc);
	}

	.filter-chip.active {
		background: var(--pf-t--global--color--brand--default, #0066cc);
		border-color: var(--pf-t--global--color--brand--default, #0066cc);
		color: #fff;
	}

	.search-input {
		width: 200px;
		padding: 3px 10px;
		border-radius: 14px;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		background: var(--pf-t--global--background--color--primary--default, #fff);
		font-size: 0.75rem;
		color: inherit;
	}

	.search-input:focus {
		outline: none;
		border-color: var(--pf-t--global--color--brand--default, #0066cc);
	}

	/* Actions area (right-aligned) */
	.filter-actions {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-left: auto;
	}

	.more-filters-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 4px 10px;
		border-radius: 14px;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		background: var(--pf-t--global--background--color--primary--default, #fff);
		font-size: 0.75rem;
		cursor: pointer;
		transition:
			background 0.15s,
			border-color 0.15s;
		color: inherit;
	}

	.more-filters-btn:hover {
		border-color: var(--pf-t--global--color--brand--default, #0066cc);
	}

	.more-filters-btn--active {
		background: var(--pf-t--global--color--brand--default, #0066cc);
		border-color: var(--pf-t--global--color--brand--default, #0066cc);
		color: #fff;
	}

	.filter-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 16px;
		height: 16px;
		padding: 0 4px;
		border-radius: 8px;
		font-size: 0.65rem;
		font-weight: 700;
		background: rgba(255, 255, 255, 0.3);
		color: inherit;
	}

	.clear-filters-btn {
		padding: 4px 10px;
		border: none;
		background: none;
		font-size: 0.75rem;
		color: var(--pf-t--global--color--link--default, #0066cc);
		cursor: pointer;
		white-space: nowrap;
	}

	.clear-filters-btn:hover {
		text-decoration: underline;
	}

	/* Active filter pills */
	.filter-pills {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		padding: 8px 16px;
		border-top: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		background: var(--pf-t--global--background--color--primary--default, #fff);
	}

	.filter-pill {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 6px 2px 8px;
		border-radius: 12px;
		font-size: 0.72rem;
		background: var(--sc-blue-bg);
		color: var(--sc-blue-text);
		border: 1px solid var(--sc-blue-border);
		white-space: nowrap;
	}

	.filter-pill__remove {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: transparent;
		color: inherit;
		cursor: pointer;
		opacity: 0.6;
		transition:
			opacity 0.15s,
			background 0.15s;
	}

	.filter-pill__remove:hover {
		opacity: 1;
		background: rgba(0, 61, 115, 0.1);
	}
</style>
