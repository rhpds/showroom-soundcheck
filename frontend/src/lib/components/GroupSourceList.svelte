<script lang="ts">
	import StatusBadge from './StatusBadge.svelte';
	import Modal from './Modal.svelte';
	import type { GroupPublic, GroupRunPublic, SessionListItem, Status } from '$lib/types';

	let {
		group,
		runs,
		runSessions,
		syncing,
		runningAll,
		onRunAll,
		onRunSource,
		onAddSource,
		onRemoveSource,
		onSync,
		onError
	}: {
		group: GroupPublic;
		runs: GroupRunPublic[];
		runSessions: Record<string, SessionListItem[]>;
		syncing: boolean;
		runningAll: boolean;
		onRunAll: () => void;
		onRunSource: (type: string, value: string) => void;
		onAddSource: (type: string, value: string) => Promise<void>;
		onRemoveSource: (type: string, value: string) => Promise<void>;
		onSync: () => void;
		onError: (msg: string) => void;
	} = $props();

	let sourcesCollapsed = $state(true);
	let showAddSource = $state(false);
	let addType = $state('workshop_guid');
	let addValue = $state('');
	let confirmRemove = $state<{ type: string; value: string } | null>(null);

	interface GroupSource {
		type: string;
		value: string;
		meta: Record<string, unknown>;
		lastStatus: Status | null;
	}

	function sourceTypeLabel(type: string): string {
		if (type === 'workshop_guid') return 'Workshop';
		if (type === 'rc_guid') return 'ResourceClaim';
		if (type === 'pool') return 'Pool';
		return type;
	}

	function sourceTypeColor(type: string): string {
		if (type === 'workshop_guid') return 'pf-m-blue';
		if (type === 'rc_guid') return 'pf-m-purple';
		if (type === 'pool') return 'pf-m-orange';
		return '';
	}

	function sourceSessionName(type: string, value: string): string {
		if (type === 'rc_guid') return `RC: ${value}`;
		if (type === 'workshop_guid') return `Workshop: ${value}`;
		if (type === 'pool') return `Pool: ${value}`;
		return value;
	}

	function getLastStatusForSource(type: string, value: string): Status | null {
		if (runs.length === 0) return null;
		const expectedName = sourceSessionName(type, value);
		for (const run of runs) {
			const sessions = runSessions[run.run_id] || [];
			const match = sessions.find((s) => s.name === expectedName);
			if (match) return match.status;
		}
		return null;
	}

	function getSources(): GroupSource[] {
		const metaMap = group.source_metadata || {};
		const sources: GroupSource[] = [];
		for (const guid of group.source_guids) {
			sources.push({
				type: 'rc_guid',
				value: guid,
				meta: metaMap[`rc_guid:${guid}`] || {},
				lastStatus: getLastStatusForSource('rc_guid', guid)
			});
		}
		for (const guid of group.source_workshop_guids) {
			sources.push({
				type: 'workshop_guid',
				value: guid,
				meta: metaMap[`workshop_guid:${guid}`] || {},
				lastStatus: getLastStatusForSource('workshop_guid', guid)
			});
		}
		for (const pool of group.source_resource_pools) {
			sources.push({
				type: 'pool',
				value: pool,
				meta: metaMap[`pool:${pool}`] || {},
				lastStatus: getLastStatusForSource('pool', pool)
			});
		}
		return sources;
	}

	let sources = $derived(getSources());

	let metadataSyncing = $derived(
		sources.length > 0 && sources.some((s) => Object.keys(s.meta).length === 0)
	);

	interface SourcesSummary {
		byType: { label: string; count: number }[];
		byStatus: { label: string; count: number; color: string }[];
	}

	let sourcesSummary = $derived.by((): SourcesSummary => {
		const typeCounts = new Map<string, number>();
		const statusCounts = new Map<string, number>();
		for (const m of sources) {
			const tl = sourceTypeLabel(m.type);
			typeCounts.set(tl, (typeCounts.get(tl) || 0) + 1);

			let s = 'unknown';
			if (m.meta.not_found) s = 'not_found';
			else if (m.meta.lookup_error) s = 'lookup_error';
			else if (m.lastStatus) s = m.lastStatus;
			statusCounts.set(s, (statusCounts.get(s) || 0) + 1);
		}

		const statusMeta: Record<string, { label: string; color: string }> = {
			healthy: { label: 'Healthy', color: 'pf-m-green' },
			completed: { label: 'All Passed', color: 'pf-m-green' },
			degraded: { label: 'Degraded', color: 'pf-m-orange' },
			error: { label: 'Error', color: 'pf-m-red' },
			unhealthy: { label: 'Unhealthy', color: 'pf-m-red' },
			failed: { label: 'Issues Found', color: 'pf-m-red' },
			running: { label: 'Running', color: 'pf-m-blue' },
			pending: { label: 'Pending', color: 'pf-m-gold' },
			not_found: { label: 'Not Found', color: 'pf-m-red' },
			lookup_error: { label: 'Lookup Error', color: 'pf-m-red' },
			unknown: { label: 'No Status', color: '' }
		};

		return {
			byType: [...typeCounts.entries()].map(([label, count]) => ({ label, count })),
			byStatus: [...statusCounts.entries()]
				.filter(([s]) => s !== 'unknown')
				.map(([s, count]) => ({
					label: statusMeta[s]?.label ?? s,
					count,
					color: statusMeta[s]?.color ?? ''
				}))
		};
	});

	async function doAddSource(e: SubmitEvent) {
		e.preventDefault();
		if (!addValue.trim()) return;
		try {
			await onAddSource(addType, addValue.trim());
			addValue = '';
			showAddSource = false;
		} catch (err) {
			onError(err instanceof Error ? err.message : 'Failed to add source');
		}
	}

	async function doRemoveSource() {
		if (!confirmRemove) return;
		const { type, value } = confirmRemove;
		confirmRemove = null;
		try {
			await onRemoveSource(type, value);
		} catch (err) {
			onError(err instanceof Error ? err.message : 'Failed to remove source');
		}
	}
</script>

<div class="group-section">
	<div
		class="group-section__header group-section__header--toggle"
		class:group-section__header--expanded={!sourcesCollapsed}
	>
		<button
			class="group-section__toggle"
			onclick={() => (sourcesCollapsed = !sourcesCollapsed)}
			aria-expanded={!sourcesCollapsed}
			aria-label={sourcesCollapsed ? 'Expand sources' : 'Collapse sources'}
		>
			<span class="group-section__chevron">
				{#if sourcesCollapsed}
					<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"
						><path d="M6 3l5 5-5 5V3Z" /></svg
					>
				{:else}
					<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"
						><path d="M3 6l5 5 5-5H3Z" /></svg
					>
				{/if}
			</span>
			<h2 class="pf-v6-c-title pf-m-lg">Sources ({sources.length})</h2>
		</button>
		{#if sourcesCollapsed && sources.length > 0}
			<span class="sources-summary">
				<span class="sources-summary__types">
					{#each sourcesSummary.byType as entry}
						<span
							class="source-type-badge {entry.label === 'Workshop'
								? 'pf-m-blue'
								: entry.label === 'ResourceClaim'
									? 'pf-m-purple'
									: entry.label === 'Pool'
										? 'pf-m-orange'
										: ''}"
						>
							{#if entry.label === 'Workshop'}
								<svg
									viewBox="0 0 16 16"
									width="12"
									height="12"
									fill="currentColor"
									aria-hidden="true"
									><path
										d="M2 3a1 1 0 0 1 1-1h4.586a1 1 0 0 1 .707.293l.707.707H13a1 1 0 0 1 1 1v2h-1V4H8.586l-.707-.707H3v9h5v1H3a1 1 0 0 1-1-1V3Zm8 5.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .354.854l-2 2a.5.5 0 0 1-.708 0l-2-2A.5.5 0 0 1 10 8.5ZM10.5 11a.5.5 0 0 0-.354.854l2 2a.5.5 0 0 0 .708 0l2-2A.5.5 0 0 0 14.5 11h-4Z"
									/></svg
								>
							{:else if entry.label === 'Pool'}
								<svg
									viewBox="0 0 16 16"
									width="12"
									height="12"
									fill="currentColor"
									aria-hidden="true"
									><path
										d="M8 1.5c-3.314 0-6 1.12-6 2.5v8c0 1.38 2.686 2.5 6 2.5s6-1.12 6-2.5V4c0-1.38-2.686-2.5-6-2.5ZM3 7.08c1.274.57 3.044.92 5 .92s3.726-.35 5-.92V9c0 .69-2.015 1.5-5 1.5S3 9.69 3 9V7.08ZM8 6c-2.985 0-5-.81-5-1.5S5.015 3 8 3s5 .81 5 1.5S10.985 6 8 6Zm0 8c-2.985 0-5-.81-5-1.5v-1.92c1.274.57 3.044.92 5 .92s3.726-.35 5-.92V12.5c0 .69-2.015 1.5-5 1.5Z"
									/></svg
								>
							{:else}
								<svg
									viewBox="0 0 16 16"
									width="12"
									height="12"
									fill="currentColor"
									aria-hidden="true"
									><path
										d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm-.5 3.25a.5.5 0 0 1 1 0v1.5h1.5a.5.5 0 0 1 0 1h-1.5v1.5a.5.5 0 0 1-1 0v-1.5H6a.5.5 0 0 1 0-1h1.5v-1.5Z"
									/></svg
								>
							{/if}
							<span>{entry.count} {entry.label}{entry.count !== 1 ? 's' : ''}</span>
						</span>
					{/each}
				</span>
				{#if sourcesSummary.byStatus.length > 0}
					<span class="sources-summary__divider">—</span>
					<span class="sources-summary__statuses">
						{#each sourcesSummary.byStatus as entry}
							{#if entry.label === 'Not Found'}
								<span class="sources-summary__not-found">
									<svg
										viewBox="0 0 16 16"
										width="12"
										height="12"
										fill="currentColor"
										aria-hidden="true"
										><path
											d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1ZM2 8a6 6 0 0 1 9.74-4.69L3.31 11.74A5.97 5.97 0 0 1 2 8Zm2.26 4.69L12.69 4.26A6 6 0 0 1 4.26 12.69Z"
										/></svg
									>
									<span>{entry.count} not found</span>
								</span>
							{:else}
								<span
									class="sources-summary__badge sources-summary__badge--{entry.color.replace(
										'pf-m-',
										''
									) || 'grey'}"
								>
									{#if entry.color === 'pf-m-green'}
										<svg
											viewBox="0 0 16 16"
											width="11"
											height="11"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm3.36 4.65a.5.5 0 0 0-.72-.02L7.2 8.94 5.35 7.17a.5.5 0 1 0-.7.71l2.2 2.12a.5.5 0 0 0 .7-.01l3.8-3.63a.5.5 0 0 0 .01-.71Z"
											/></svg
										>
									{:else if entry.color === 'pf-m-red'}
										<svg
											viewBox="0 0 16 16"
											width="11"
											height="11"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm2.35 4.65a.5.5 0 0 0-.7 0L8 7.29 6.35 5.65a.5.5 0 1 0-.7.7L7.29 8 5.65 9.65a.5.5 0 1 0 .7.7L8 8.71l1.65 1.64a.5.5 0 0 0 .7-.7L8.71 8l1.64-1.65a.5.5 0 0 0 0-.7Z"
											/></svg
										>
									{:else if entry.color === 'pf-m-blue'}
										<svg
											viewBox="0 0 16 16"
											width="11"
											height="11"
											fill="currentColor"
											aria-hidden="true"
											><path d="M8 1.5a6.5 6.5 0 1 0 6.5 6.5h-1.3A5.2 5.2 0 1 1 8 2.8V1.5Z" /></svg
										>
									{:else if entry.color === 'pf-m-orange'}
										<svg
											viewBox="0 0 16 16"
											width="11"
											height="11"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
											/></svg
										>
									{:else if entry.color === 'pf-m-gold'}
										<svg
											viewBox="0 0 16 16"
											width="11"
											height="11"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm.5 3a.5.5 0 0 0-1 0v4.25l2.9 1.74a.5.5 0 0 0 .51-.86L8.5 7.68V4Z"
											/></svg
										>
									{:else}
										<svg
											viewBox="0 0 16 16"
											width="11"
											height="11"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm.5 3a.5.5 0 0 0-1 0v4.25l2.9 1.74a.5.5 0 0 0 .51-.86L8.5 7.68V4Z"
											/></svg
										>
									{/if}
									<span>{entry.count} {entry.label}</span>
								</span>
							{/if}
						{/each}
					</span>
				{/if}
			</span>
		{/if}
		<div class="group-section__actions">
			<button
				class="pf-v6-c-button pf-m-plain pf-m-sm"
				onclick={onSync}
				disabled={syncing || metadataSyncing}
				aria-label="Sync metadata"
			>
				<svg
					viewBox="0 0 16 16"
					width="14"
					height="14"
					fill="currentColor"
					class:spin-icon={syncing || metadataSyncing}
					><path
						d="M2.5 8a5.5 5.5 0 0 1 9.23-4.042l-1.023.375A4.5 4.5 0 0 0 3.5 8h2L3 11 .5 8h2Zm11 0h-2L14 5l2.5 3h-2a5.5 5.5 0 0 1-9.23 4.042l1.023-.375A4.5 4.5 0 0 0 13.5 8Z"
					/></svg
				>
			</button>
			<button class="pf-v6-c-button pf-m-secondary pf-m-sm" onclick={() => (showAddSource = true)}
				>+ Add</button
			>
			<button class="pf-v6-c-button pf-m-primary pf-m-sm" onclick={onRunAll} disabled={runningAll}>
				{#if runningAll}Running...{:else}<svg
						viewBox="0 0 16 16"
						width="12"
						height="12"
						fill="currentColor"
						aria-hidden="true"
						style="margin-right: 4px;"
						><path
							d="M4 2.5a.5.5 0 0 1 .776-.416l8.5 5.5a.5.5 0 0 1 0 .832l-8.5 5.5A.5.5 0 0 1 4 13.5v-11Z"
						/></svg
					> Run All{/if}
			</button>
		</div>
	</div>
	{#if !sourcesCollapsed}
		<div class="group-section__body">
			{#if sources.length === 0}
				<p class="group-empty">No sources yet. Add GUIDs or pools to get started.</p>
			{:else}
				<ul class="source-list" role="list">
					{#each sources as source}
						<li
							class="source-list__item"
							class:source-list__item--not-found={!!source.meta.not_found}
							role="listitem"
						>
							<div class="source-list__main">
								<span class="source-type-badge {sourceTypeColor(source.type)}">
									{#if source.type === 'workshop_guid'}
										<svg
											viewBox="0 0 16 16"
											width="12"
											height="12"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M2 3a1 1 0 0 1 1-1h4.586a1 1 0 0 1 .707.293l.707.707H13a1 1 0 0 1 1 1v2h-1V4H8.586l-.707-.707H3v9h5v1H3a1 1 0 0 1-1-1V3Zm8 5.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .354.854l-2 2a.5.5 0 0 1-.708 0l-2-2A.5.5 0 0 1 10 8.5ZM10.5 11a.5.5 0 0 0-.354.854l2 2a.5.5 0 0 0 .708 0l2-2A.5.5 0 0 0 14.5 11h-4Z"
											/></svg
										>
									{:else if source.type === 'pool'}
										<svg
											viewBox="0 0 16 16"
											width="12"
											height="12"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M8 1.5c-3.314 0-6 1.12-6 2.5v8c0 1.38 2.686 2.5 6 2.5s6-1.12 6-2.5V4c0-1.38-2.686-2.5-6-2.5ZM3 7.08c1.274.57 3.044.92 5 .92s3.726-.35 5-.92V9c0 .69-2.015 1.5-5 1.5S3 9.69 3 9V7.08ZM8 6c-2.985 0-5-.81-5-1.5S5.015 3 8 3s5 .81 5 1.5S10.985 6 8 6Zm0 8c-2.985 0-5-.81-5-1.5v-1.92c1.274.57 3.044.92 5 .92s3.726-.35 5-.92V12.5c0 .69-2.015 1.5-5 1.5Z"
											/></svg
										>
									{:else}
										<svg
											viewBox="0 0 16 16"
											width="12"
											height="12"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm-.5 3.25a.5.5 0 0 1 1 0v1.5h1.5a.5.5 0 0 1 0 1h-1.5v1.5a.5.5 0 0 1-1 0v-1.5H6a.5.5 0 0 1 0-1h1.5v-1.5Z"
											/></svg
										>
									{/if}
									<span>{sourceTypeLabel(source.type)}</span>
								</span>
								{#if source.meta.not_found}
									<span class="source-list__missing-icon" title="Not found">
										<svg
											viewBox="0 0 16 16"
											width="14"
											height="14"
											fill="currentColor"
											aria-hidden="true"
											><path
												d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1ZM2 8a6 6 0 0 1 9.74-4.69L3.31 11.74A5.97 5.97 0 0 1 2 8Zm2.26 4.69L12.69 4.26A6 6 0 0 1 4.26 12.69Z"
											/></svg
										>
									</span>
								{:else if source.meta.lookup_error}
									<span
										class="pf-v6-c-label pf-m-compact pf-m-red"
										title={String(source.meta.lookup_error)}
									>
										<span class="pf-v6-c-label__content"
											><span class="pf-v6-c-label__text">Lookup Error</span></span
										>
									</span>
								{:else if source.lastStatus}
									<StatusBadge status={source.lastStatus} size="sm" />
								{/if}
								<span class="source-list__value">{source.value}</span>
								{#if !source.meta.not_found && !source.meta.lookup_error && (source.meta.display_name || source.meta.catalog_item) && (source.meta.display_name || source.meta.catalog_item) !== source.value}
									<span class="source-list__description"
										>{source.meta.display_name || source.meta.catalog_item}</span
									>
								{/if}
							</div>
							<div class="source-list__actions">
								{#if source.meta.catalog_url}
									<a
										class="pf-v6-c-button pf-m-plain pf-m-sm"
										href={String(source.meta.catalog_url)}
										target="_blank"
										rel="noopener noreferrer"
										aria-label="Open in catalog"
									>
										<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
											><path
												d="M9 2a.5.5 0 0 1 0-1h5.5a.5.5 0 0 1 .5.5V7a.5.5 0 0 1-1 0V2.707l-5.146 5.147a.5.5 0 0 1-.708-.708L13.293 2H9ZM3.5 4A1.5 1.5 0 0 0 2 5.5v7A1.5 1.5 0 0 0 3.5 14h7a1.5 1.5 0 0 0 1.5-1.5V9a.5.5 0 0 1 1 0v3.5a2.5 2.5 0 0 1-2.5 2.5h-7A2.5 2.5 0 0 1 1 12.5v-7A2.5 2.5 0 0 1 3.5 3H7a.5.5 0 0 1 0 1H3.5Z"
											/></svg
										>
									</a>
								{/if}
								{#if !source.meta.not_found}
									<button
										class="pf-v6-c-button pf-m-plain pf-m-sm"
										onclick={() => onRunSource(source.type, source.value)}
										aria-label="Run check"
									>
										<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
											><path
												d="M4 2.5a.5.5 0 0 1 .776-.416l8.5 5.5a.5.5 0 0 1 0 .832l-8.5 5.5A.5.5 0 0 1 4 13.5v-11Z"
											/></svg
										>
									</button>
								{/if}
								<button
									class="pf-v6-c-button pf-m-plain pf-m-sm"
									onclick={() => (confirmRemove = { type: source.type, value: source.value })}
									aria-label="Remove"
								>
									<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
										><path
											d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708Z"
										/></svg
									>
								</button>
							</div>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
</div>

{#if showAddSource}
	<Modal title="Add Source" size="sm" onClose={() => (showAddSource = false)}>
		<form onsubmit={doAddSource}>
			<div class="pf-v6-c-form">
				<div class="pf-v6-c-form__group">
					<label class="pf-v6-c-form__label" for="add-type">Type</label>
					<span class="pf-v6-c-form-control">
						<select id="add-type" bind:value={addType}>
							<option value="workshop_guid">Workshop GUID</option>
							<option value="rc_guid">ResourceClaim GUID</option>
							<option value="pool">ResourcePool</option>
						</select>
					</span>
				</div>
				<div class="pf-v6-c-form__group">
					<label class="pf-v6-c-form__label" for="add-value">Value</label>
					<span class="pf-v6-c-form-control">
						<input id="add-value" bind:value={addValue} required />
					</span>
				</div>
				<div class="pf-v6-u-display-flex pf-v6-u-justify-content-flex-end pf-v6-u-gap-sm">
					<button
						class="pf-v6-c-button pf-m-link"
						type="button"
						onclick={() => (showAddSource = false)}>Cancel</button
					>
					<button class="pf-v6-c-button pf-m-primary" type="submit">Add</button>
				</div>
			</div>
		</form>
	</Modal>
{/if}

{#if confirmRemove}
	<Modal title="Remove Source" size="sm" onClose={() => (confirmRemove = null)}>
		<p class="pf-v6-u-mb-md">
			Remove <strong>{sourceTypeLabel(confirmRemove.type)}: {confirmRemove.value}</strong> from this group?
		</p>
		<div class="pf-v6-u-display-flex pf-v6-u-justify-content-flex-end pf-v6-u-gap-sm">
			<button class="pf-v6-c-button pf-m-link" type="button" onclick={() => (confirmRemove = null)}
				>Cancel</button
			>
			<button class="pf-v6-c-button pf-m-danger" type="button" onclick={doRemoveSource}
				>Remove</button
			>
		</div>
	</Modal>
{/if}

<style>
	.group-section {
		background: var(--pf-t--global--background--color--primary--default, #fff);
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
	}

	.group-section__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--pf-t--global--spacer--md, 16px) var(--pf-t--global--spacer--lg, 24px);
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.group-section__header--toggle {
		flex-wrap: wrap;
		gap: 8px;
	}

	.group-section__header--toggle.group-section__header--expanded {
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.group-section__header--toggle:not(.group-section__header--expanded) {
		border-bottom: none;
	}

	.group-section__toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font: inherit;
		text-align: left;
	}

	.group-section__toggle:hover {
		color: var(--pf-t--global--color--brand--default, #0066cc);
	}

	.group-section__chevron {
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		flex-shrink: 0;
		width: 1em;
	}

	.group-section__actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.group-section__body {
		padding: var(--pf-t--global--spacer--md, 16px) var(--pf-t--global--spacer--lg, 24px);
	}

	.group-empty {
		text-align: center;
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		padding: var(--pf-t--global--spacer--lg, 24px) 0;
		margin: 0;
	}

	.sources-summary {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		flex-wrap: wrap;
		min-width: 0;
	}

	.sources-summary__types {
		display: flex;
		align-items: center;
		gap: 4px;
		white-space: nowrap;
	}

	.sources-summary__divider {
		margin: 0 2px;
	}

	.sources-summary__statuses {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-wrap: wrap;
	}

	.sources-summary__not-found {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		opacity: 0.55;
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
	}

	.sources-summary__badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 8px;
		border-radius: 12px;
		font-size: 0.75rem;
		font-weight: 500;
		border: 1px solid;
	}

	.sources-summary__badge--green {
		color: var(--sc-green-text);
		background: var(--sc-green-bg);
		border-color: var(--sc-green-border);
	}
	.sources-summary__badge--red {
		color: var(--sc-red-text);
		background: var(--sc-red-bg);
		border-color: var(--sc-red-border);
	}
	.sources-summary__badge--blue {
		color: var(--sc-blue-text);
		background: var(--sc-blue-bg);
		border-color: var(--sc-blue-border);
	}
	.sources-summary__badge--orange {
		color: var(--sc-orange-text);
		background: var(--sc-orange-bg);
		border-color: var(--sc-orange-border);
	}
	.sources-summary__badge--gold {
		color: var(--sc-gold-text);
		background: var(--sc-gold-bg);
		border-color: var(--sc-gold-border);
	}
	.sources-summary__badge--grey,
	.sources-summary__badge-- {
		color: #3c3f42;
		background: #f5f5f5;
		border-color: #d2d2d2;
	}

	.source-list {
		list-style: none;
		padding: 0;
		margin: 0;
	}

	.source-list__item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 10px 0;
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.source-list__item:last-child {
		border-bottom: none;
	}

	.source-list__item--not-found {
		opacity: 0.5;
	}

	.source-list__item--not-found .source-list__value {
		text-decoration: line-through;
	}

	.source-list__missing-icon {
		display: inline-flex;
		align-items: center;
		color: var(--pf-t--global--color--status--danger--default, #c9190b);
	}

	.source-list__main {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		flex-wrap: wrap;
	}

	.source-list__value {
		font-weight: 600;
		word-break: break-all;
	}

	.source-list__description {
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
	}

	.source-list__actions {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.source-type-badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 8px;
		border-radius: 12px;
		font-size: 0.75rem;
		font-weight: 500;
		white-space: nowrap;
	}

	.source-type-badge.pf-m-blue {
		color: var(--sc-blue-text);
		background: var(--sc-blue-bg);
	}
	.source-type-badge.pf-m-purple {
		color: var(--sc-purple-text);
		background: var(--sc-purple-bg);
	}
	.source-type-badge.pf-m-orange {
		color: var(--sc-orange-text);
		background: var(--sc-orange-bg);
	}

	@keyframes spin {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}

	:global(.spin-icon) {
		animation: spin 1s linear infinite;
	}
</style>
