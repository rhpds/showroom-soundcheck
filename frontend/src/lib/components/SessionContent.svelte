<script lang="ts">
	import { onDestroy, tick } from 'svelte';
	import { getSession, cloneSession, sessionStream } from '$lib/api';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import TargetDetail from '$lib/components/TargetDetail.svelte';
	import type { SessionDetail, TargetPublic } from '$lib/types';
	import { ISSUE_STATUSES, IN_PROGRESS_STATUSES, TERMINAL_STATUSES, STATUS_SORT_ORDER } from '$lib/types';

	let {
		sessionId,
		onNavigate,
		onRerun
	}: {
		sessionId: string;
		onNavigate?: (sessionId: string) => void;
		onRerun?: (sourceType: string, sourceValue: string) => void;
	} = $props();

	let data = $state.raw<SessionDetail | null>(null);
	let loading = $state(true);
	let notFound = $state(false);
	let loadError = $state('');
	let filter = $state<'all' | 'issues' | 'healthy' | 'in_progress'>('all');
	let eventSource: EventSource | null = null;
	let retryTimeout: ReturnType<typeof setTimeout> | null = null;
	let retryCount = 0;
	const MAX_RETRIES = 5;
	let currentLoadId = 0;
	let abortController: AbortController | null = null;

	let selectedTargetId = $state<number | null>(null);
	let cloneError = $state('');
	let streamFailed = $state(false);

	$effect(() => {
		const _id = sessionId;
		retryCount = 0;
		filter = 'all';
		selectedTargetId = null;
		cloneError = '';
		loadError = '';
		streamFailed = false;
		loadSession();
		return () => {
			closeStream();
		};
	});

	onDestroy(() => {
		closeStream();
	});

	function closeStream() {
		abortController?.abort();
		abortController = null;
		eventSource?.close();
		eventSource = null;
		if (retryTimeout) {
			clearTimeout(retryTimeout);
			retryTimeout = null;
		}
	}

	async function loadSession() {
		const myLoadId = ++currentLoadId;
		abortController?.abort();
		abortController = new AbortController();
		loading = true;
		notFound = false;
		loadError = '';
		try {
			const result = await getSession(sessionId, { signal: abortController.signal });
			if (myLoadId !== currentLoadId) return;
			data = result;
			if (!result.session) {
				notFound = true;
			} else if (result.session.status === 'pending' || result.session.status === 'running') {
				startStreaming();
			}
		} catch (e) {
			if (myLoadId !== currentLoadId) return;
			if (e instanceof DOMException && e.name === 'AbortError') return;
			loadError = e instanceof Error ? e.message : 'Failed to load session';
		}
		loading = false;
	}

	function startStreaming() {
		closeStream();
		retryCount = 0;
		eventSource = sessionStream(sessionId);

		eventSource.onmessage = (event) => {
			try {
				const update = JSON.parse(event.data);
				if (data) {
					data = {
						session: update.session ?? { ...data.session, status: update.status },
						targets: update.targets,
						results: update.results
					};
				}
				if (update.status === 'completed' || update.status === 'failed') {
					closeStream();
				}
			} catch (e) {
				console.error('Failed to parse SSE message', e);
			}
		};

		eventSource.onerror = () => {
			eventSource?.close();
			eventSource = null;
			if (data?.session?.status === 'completed' || data?.session?.status === 'failed') {
				return;
			}
			if (retryCount < MAX_RETRIES) {
				retryCount++;
				retryTimeout = setTimeout(loadSession, 3000 * retryCount);
			} else {
				streamFailed = true;
			}
		};
	}

	async function handleClone() {
		cloneError = '';
		try {
			if (onRerun && data?.session) {
				const s = data.session;
				const sourceType = s.source_guids.length
					? 'rc_guid'
					: s.source_workshop_guids.length
						? 'workshop_guid'
						: s.source_resource_pools.length
							? 'pool'
							: null;
				const sourceValue =
					s.source_guids[0] ?? s.source_workshop_guids[0] ?? s.source_resource_pools[0];
				if (sourceType && sourceValue) {
					onRerun(sourceType, sourceValue);
					return;
				}
			}
			const result = await cloneSession(sessionId);
			if (result.session_id && onNavigate) {
				onNavigate(result.session_id);
			}
		} catch (e) {
			cloneError = e instanceof Error ? e.message : 'Failed to re-run session';
		}
	}

	function filteredTargets(targets: TargetPublic[]): TargetPublic[] {
		const sorted = [...targets].sort(
			(a, b) => (STATUS_SORT_ORDER[a.status] ?? 99) - (STATUS_SORT_ORDER[b.status] ?? 99)
		);
		if (filter === 'all') return sorted;
		if (filter === 'issues')
			return sorted.filter((t) => ISSUE_STATUSES.includes(t.status));
		if (filter === 'healthy') return sorted.filter((t) => t.status === 'healthy');
		return sorted.filter((t) => IN_PROGRESS_STATUSES.includes(t.status));
	}

	function targetCounts(targets: TargetPublic[]) {
		let healthy = 0,
			issues = 0,
			inProgress = 0;
		for (const t of targets) {
			if (t.status === 'healthy') healthy++;
			else if (ISSUE_STATUSES.includes(t.status)) issues++;
			else if (IN_PROGRESS_STATUSES.includes(t.status)) inProgress++;
		}
		return { healthy, issues, inProgress, total: targets.length };
	}

	const filterOrder: (typeof filter)[] = ['all', 'issues', 'healthy', 'in_progress'];

	function handleFilterTabKeydown(e: KeyboardEvent) {
		if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
		e.preventDefault();
		const idx = filterOrder.indexOf(filter);
		const next =
			e.key === 'ArrowRight'
				? filterOrder[(idx + 1) % filterOrder.length]
				: filterOrder[(idx - 1 + filterOrder.length) % filterOrder.length];
		filter = next;
		tick().then(() => {
			const active = (e.currentTarget as HTMLElement)
				?.closest('[role="tablist"]')
				?.querySelector<HTMLElement>('[aria-selected="true"]');
			active?.focus();
		});
	}

	let sessionTitle = $derived.by(() => {
		if (!data) return 'Health Check Session';
		const s = data.session;
		const guid =
			s.source_workshop_guids?.[0] || s.source_guids?.[0] || s.source_resource_pools?.[0];
		if (s.resource_display_name && guid) return `${s.resource_display_name} - ${guid}`;
		return s.resource_display_name || s.name || 'Health Check Session';
	});

	let targets = $derived(data ? filteredTargets(data.targets) : []);
	let counts = $derived(
		data ? targetCounts(data.targets) : { healthy: 0, issues: 0, inProgress: 0, total: 0 }
	);
	let selectedResult = $derived(
		selectedTargetId && data
			? (data.results.find((r) => r.target_id === selectedTargetId) ?? null)
			: null
	);
</script>

{#if loading}
	<div class="session-skeleton" role="status" aria-label="Loading session">
		<div class="session-header">
			<div class="session-header__top">
				<div class="session-header__title-group" style="flex: 1">
					<div class="pf-v6-c-skeleton pf-m-text-2xl" style="--pf-v6-c-skeleton--Width: 340px; max-width: 60%"></div>
					<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 80px; --pf-v6-c-skeleton--Height: 22px; border-radius: 12px"></div>
				</div>
			</div>
			<div class="session-header__meta" style="margin-top: 12px">
				<div class="pf-v6-c-skeleton pf-m-text-sm" style="--pf-v6-c-skeleton--Width: 48px"></div>
				<div class="pf-v6-c-skeleton pf-m-text-sm" style="--pf-v6-c-skeleton--Width: 150px"></div>
			</div>
			<div style="display: flex; align-items: center; gap: 8px; margin-top: 12px">
				<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 90px; --pf-v6-c-skeleton--Height: 22px; border-radius: 12px"></div>
				<div class="pf-v6-c-skeleton pf-m-text-sm" style="--pf-v6-c-skeleton--Width: 60px"></div>
			</div>
			<div class="session-header__counts" style="margin-top: 16px">
				{#each [90, 80, 72] as w}
					<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: {w}px; --pf-v6-c-skeleton--Height: 24px; border-radius: 12px"></div>
				{/each}
			</div>
		</div>
		<div class="session-targets">
			<div class="skeleton-tabs">
				{#each [48, 72, 56, 80] as w}
					<div class="pf-v6-c-skeleton pf-m-text-sm" style="--pf-v6-c-skeleton--Width: {w}px"></div>
				{/each}
			</div>
			{#each [220, 200, 190, 210, 195, 185, 205, 215] as w}
				<div class="skeleton-target-row">
					<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 56px; --pf-v6-c-skeleton--Height: 20px; border-radius: 10px"></div>
					<div class="pf-v6-c-skeleton pf-m-text-sm" style="--pf-v6-c-skeleton--Width: {w}px"></div>
					<div class="skeleton-target-row__right">
						<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 42px; --pf-v6-c-skeleton--Height: 18px; border-radius: 10px"></div>
						<div class="pf-v6-c-skeleton pf-m-text-sm" style="--pf-v6-c-skeleton--Width: 50px"></div>
					</div>
				</div>
			{/each}
		</div>
	</div>
{:else if notFound}
	<div class="pf-v6-u-text-align-center pf-v6-u-mt-2xl">
		<h2 class="pf-v6-c-title pf-m-xl">Session not found</h2>
		<p class="pf-v6-u-color-200">This session may have been deleted or the URL is incorrect.</p>
	</div>
{:else if loadError}
	<div class="pf-v6-u-text-align-center pf-v6-u-mt-2xl">
		<div class="pf-v6-c-alert pf-m-danger pf-m-inline pf-v6-u-mb-md" role="alert">
			<div class="pf-v6-c-alert__icon">
				<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true"
					><path
						d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
					/></svg
				>
			</div>
			<h4 class="pf-v6-c-alert__title">{loadError}</h4>
		</div>
		<button class="pf-v6-c-button pf-m-primary" onclick={loadSession}>Retry</button>
	</div>
{:else if data}
	<div class="session-header">
		<div class="session-header__top">
			<div class="session-header__title-group">
				<h1 class="pf-v6-c-title pf-m-2xl">
					{sessionTitle}
				</h1>
				<StatusBadge status={data.session.status} />
			</div>
			{#if data.session.status === 'completed' || data.session.status === 'failed'}
				<div class="session-header__rerun">
					<button class="pf-v6-c-button pf-m-secondary pf-m-sm" onclick={handleClone}>
						<svg
							viewBox="0 0 16 16"
							width="14"
							height="14"
							fill="currentColor"
							aria-hidden="true"
							style="margin-right: 4px;"
							><path
								d="M2.5 8a5.5 5.5 0 0 1 9.23-4.042l-1.023.375A4.5 4.5 0 0 0 3.5 8h2L3 11 .5 8h2Zm11 0h-2L14 5l2.5 3h-2a5.5 5.5 0 0 1-9.23 4.042l1.023-.375A4.5 4.5 0 0 0 13.5 8Z"
							/></svg
						>
						Re-run
					</button>
					{#if cloneError}
						<span class="session-header__clone-error" role="alert">{cloneError}</span>
					{/if}
				</div>
			{/if}
		</div>

		<div class="session-header__meta">
			<span class="session-meta-item">{new Date(data.session.created_at).toLocaleString()}</span>
		</div>

		{#if data.session.group_id || data.session.resource_kind}
			<div class="session-header__context">
				{#if data.session.group_id}
					<a href="/group/{data.session.group_id}" class="context-chip context-chip--teal">
						<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"
							><path
								d="M1 3.5A1.5 1.5 0 0 1 2.5 2h3.879a1.5 1.5 0 0 1 1.06.44l1.122 1.12H13.5A1.5 1.5 0 0 1 15 5v7.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12.5v-9ZM2.5 3a.5.5 0 0 0-.5.5v9a.5.5 0 0 0 .5.5h11a.5.5 0 0 0 .5-.5V5a.5.5 0 0 0-.5-.5H8.561a.5.5 0 0 1-.354-.146L7.086 3.232A.5.5 0 0 0 6.732 3H2.5Z"
							/></svg
						>
						Group
					</a>
				{/if}
				{#if data.session.resource_kind}
					<span
						class="context-chip {data.session.resource_kind === 'Workshop'
							? 'context-chip--blue'
							: data.session.resource_kind === 'ResourcePool'
								? 'context-chip--orange'
								: 'context-chip--purple'}"
					>
						{#if data.session.resource_kind === 'Workshop'}
							<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"
								><path
									d="M2 3a1 1 0 0 1 1-1h4.586a1 1 0 0 1 .707.293l.707.707H13a1 1 0 0 1 1 1v2h-1V4H8.586l-.707-.707H3v9h5v1H3a1 1 0 0 1-1-1V3Zm8 5.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 .354.854l-2 2a.5.5 0 0 1-.708 0l-2-2A.5.5 0 0 1 10 8.5ZM10.5 11a.5.5 0 0 0-.354.854l2 2a.5.5 0 0 0 .708 0l2-2A.5.5 0 0 0 14.5 11h-4Z"
								/></svg
							>
						{:else if data.session.resource_kind === 'ResourcePool'}
							<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"
								><path
									d="M8 1.5c-3.314 0-6 1.12-6 2.5v8c0 1.38 2.686 2.5 6 2.5s6-1.12 6-2.5V4c0-1.38-2.686-2.5-6-2.5ZM3 7.08c1.274.57 3.044.92 5 .92s3.726-.35 5-.92V9c0 .69-2.015 1.5-5 1.5S3 9.69 3 9V7.08ZM8 6c-2.985 0-5-.81-5-1.5S5.015 3 8 3s5 .81 5 1.5S10.985 6 8 6Zm0 8c-2.985 0-5-.81-5-1.5v-1.92c1.274.57 3.044.92 5 .92s3.726-.35 5-.92V12.5c0 .69-2.015 1.5-5 1.5Z"
								/></svg
							>
						{:else}
							<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"
								><path
									d="M4 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4Zm4 3a.75.75 0 0 1 .75.75v1.5h1.5a.75.75 0 0 1 0 1.5h-1.5v1.5a.75.75 0 0 1-1.5 0v-1.5h-1.5a.75.75 0 0 1 0-1.5h1.5v-1.5A.75.75 0 0 1 8 5Z"
								/></svg
							>
						{/if}
						{data.session.resource_kind}
					</span>
				{/if}
				{#if data.session.source_workshop_guids?.[0] || data.session.source_guids?.[0] || data.session.source_resource_pools?.[0]}
					<span class="context-guid"
						>{data.session.source_workshop_guids?.[0] ||
							data.session.source_guids?.[0] ||
							data.session.source_resource_pools?.[0]}</span
					>
				{/if}
			</div>
		{/if}

		<div class="session-header__counts">
			{#if counts.issues > 0}
				<span class="count-badge count-badge--red">
					<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"
						><path
							d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm2.35 4.65a.5.5 0 0 0-.7 0L8 7.29 6.35 5.65a.5.5 0 1 0-.7.7L7.29 8 5.65 9.65a.5.5 0 1 0 .7.7L8 8.71l1.65 1.64a.5.5 0 0 0 .7-.7L8.71 8l1.64-1.65a.5.5 0 0 0 0-.7Z"
						/></svg
					>
					<span>{counts.issues} Issues</span>
				</span>
			{/if}
			{#if counts.healthy > 0}
				<span class="count-badge count-badge--green">
					<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"
						><path
							d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm3.36 4.65a.5.5 0 0 0-.72-.02L7.2 8.94 5.35 7.17a.5.5 0 1 0-.7.71l2.2 2.12a.5.5 0 0 0 .7-.01l3.8-3.63a.5.5 0 0 0 .01-.71Z"
						/></svg
					>
					<span>{counts.healthy} Healthy</span>
				</span>
			{/if}
			{#if counts.inProgress > 0}
				<span class="count-badge count-badge--blue">
					<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"
						><path d="M8 1.5a6.5 6.5 0 1 0 6.5 6.5h-1.3A5.2 5.2 0 1 1 8 2.8V1.5Z" /></svg
					>
					<span>{counts.inProgress} In Progress</span>
				</span>
			{/if}
			<span class="count-badge count-badge--grey">
				<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" aria-hidden="true"
					><path
						d="M2 4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4Zm3.5 1a.5.5 0 0 0 0 1h5a.5.5 0 0 0 0-1h-5Zm0 2.5a.5.5 0 0 0 0 1h5a.5.5 0 0 0 0-1h-5Zm0 2.5a.5.5 0 0 0 0 1h3a.5.5 0 0 0 0-1h-3Z"
					/></svg
				>
				<span>{counts.total} Targets</span>
			</span>
		</div>
	</div>

	{#if data.session.status === 'running' || data.session.status === 'pending'}
		{@const checked = data.targets.filter((t) => TERMINAL_STATUSES.includes(t.status)).length}
		{@const percent = counts.total ? Math.round((checked / counts.total) * 100) : 0}
		<div class="session-progress">
			<Spinner label="Checking targets" size="sm" />
			<span class="session-progress__text">Checking {checked} of {counts.total} targets...</span>
			<div class="session-progress__bar">
				<div
					class="session-progress__bar-track"
					role="progressbar"
					aria-valuemin={0}
					aria-valuemax={100}
					aria-valuenow={percent}
				>
					<div class="session-progress__bar-fill" style="width: {percent}%"></div>
				</div>
			</div>
		</div>
	{/if}

	{#if streamFailed}
		<div class="session-stream-notice" role="status">
			<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"
				><path
					d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
				/></svg
			>
			<span>Live updates paused.</span>
			<button
				class="pf-v6-c-button pf-m-link pf-m-inline pf-m-sm"
				onclick={() => {
					streamFailed = false;
					loadSession();
				}}
			>
				Retry
			</button>
		</div>
	{/if}

	{#if data.targets.length > 0}
		<div class="session-targets">
			<div class="pf-v6-c-tabs" role="tablist">
				<ul class="pf-v6-c-tabs__list">
					<li class="pf-v6-c-tabs__item" class:pf-m-current={filter === 'all'} role="presentation">
						<button
							class="pf-v6-c-tabs__link"
							role="tab"
							id="filter-tab-all"
							aria-selected={filter === 'all'}
							tabindex={filter === 'all' ? 0 : -1}
							onclick={() => (filter = 'all')}
							onkeydown={handleFilterTabKeydown}
						>
							<span class="pf-v6-c-tabs__item-text">All ({counts.total})</span>
						</button>
					</li>
					<li
						class="pf-v6-c-tabs__item"
						class:pf-m-current={filter === 'issues'}
						role="presentation"
					>
						<button
							class="pf-v6-c-tabs__link"
							role="tab"
							id="filter-tab-issues"
							aria-selected={filter === 'issues'}
							tabindex={filter === 'issues' ? 0 : -1}
							onclick={() => (filter = 'issues')}
							onkeydown={handleFilterTabKeydown}
						>
							<span class="pf-v6-c-tabs__item-text">Issues ({counts.issues})</span>
						</button>
					</li>
					<li
						class="pf-v6-c-tabs__item"
						class:pf-m-current={filter === 'healthy'}
						role="presentation"
					>
						<button
							class="pf-v6-c-tabs__link"
							role="tab"
							id="filter-tab-healthy"
							aria-selected={filter === 'healthy'}
							tabindex={filter === 'healthy' ? 0 : -1}
							onclick={() => (filter = 'healthy')}
							onkeydown={handleFilterTabKeydown}
						>
							<span class="pf-v6-c-tabs__item-text">Healthy ({counts.healthy})</span>
						</button>
					</li>
					<li
						class="pf-v6-c-tabs__item"
						class:pf-m-current={filter === 'in_progress'}
						role="presentation"
					>
						<button
							class="pf-v6-c-tabs__link"
							role="tab"
							id="filter-tab-in_progress"
							aria-selected={filter === 'in_progress'}
							tabindex={filter === 'in_progress' ? 0 : -1}
							onclick={() => (filter = 'in_progress')}
							onkeydown={handleFilterTabKeydown}
						>
							<span class="pf-v6-c-tabs__item-text">In Progress ({counts.inProgress})</span>
						</button>
					</li>
				</ul>
			</div>

			<div role="tabpanel" aria-labelledby="filter-tab-{filter}">
				<ul class="target-list" role="list">
					{#each targets as target (target.id)}
						<li class="target-list__item">
							<button
								class="target-list__button"
								disabled={target.status === 'provisioning'}
								onclick={() => { selectedTargetId = target.id; }}
							>
								<div class="target-list__main">
									<StatusBadge status={target.status} size="sm" />
									<div class="target-list__content">
										<span class="target-list__label">{target.label || target.url || 'No URL'}</span>
										{#if target.error_message}
											<span class="target-list__error">{target.error_message}</span>
										{/if}
									</div>
								</div>
								<div class="target-list__meta">
									{#if target.guid}
										<span class="guid-badge guid-badge--purple">{target.guid}</span>
									{/if}
									{#if target.tier_used}
										<span class="pf-v6-c-label pf-m-compact"
											><span class="pf-v6-c-label__content"
												><span class="pf-v6-c-label__text">T{target.tier_used}</span></span
											></span
										>
									{/if}
									{#if target.response_time_ms}
										<span class="target-list__time">{target.response_time_ms}ms</span>
									{/if}
									{#if target.status !== 'provisioning'}
										<span class="target-list__chevron">
											<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
												><path d="M6 3l5 5-5 5V3Z" /></svg
											>
										</span>
									{/if}
								</div>
							</button>
						</li>
					{/each}
				</ul>
			</div>
		</div>
	{/if}

	{#if selectedTargetId}
		<TargetDetail
			target={data.targets.find((t) => t.id === selectedTargetId) ?? null}
			result={selectedResult}
			onClose={() => (selectedTargetId = null)}
		/>
	{/if}
{/if}

<style>
	.skeleton-tabs {
		display: flex;
		gap: 24px;
		padding: 12px var(--pf-t--global--spacer--lg, 24px);
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.skeleton-target-row {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 12px var(--pf-t--global--spacer--lg, 24px);
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.skeleton-target-row:last-child {
		border-bottom: none;
	}

	.skeleton-target-row__right {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-left: auto;
	}

	.session-header {
		padding: var(--pf-t--global--spacer--lg, 24px);
		background: var(--pf-t--global--background--color--primary--default, #fff);
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		margin-top: var(--pf-t--global--spacer--md, 16px);
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
	}

	.session-header__top {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
	}

	.session-header__title-group {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		min-width: 0;
	}

	.session-header__title-group h1 {
		word-break: break-word;
		margin: 0;
	}

	.session-header__meta {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		margin-top: 12px;
		padding-top: 12px;
		border-top: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.session-meta-item {
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
	}

	.session-header__context {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-top: 8px;
	}

	.context-chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 2px 10px;
		border-radius: 12px;
		font-size: 0.8125rem;
		font-weight: 500;
		border: 1px solid;
		text-decoration: none;
	}

	.context-chip svg {
		flex-shrink: 0;
	}

	a.context-chip:hover {
		text-decoration: underline;
	}

	.context-chip--teal {
		color: var(--sc-teal-text);
		background: var(--sc-teal-bg);
		border-color: var(--sc-teal-border);
	}

	.context-chip--blue {
		color: var(--sc-blue-text);
		background: var(--sc-blue-bg);
		border-color: var(--sc-blue-border);
	}

	.context-chip--orange {
		color: var(--sc-orange-text);
		background: var(--sc-orange-bg);
		border-color: var(--sc-orange-border);
	}

	.context-chip--purple {
		color: var(--sc-purple-text);
		background: var(--sc-purple-bg);
		border-color: var(--sc-purple-border);
	}

	.context-guid {
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		font-family: var(--pf-t--global--font--family--mono, monospace);
	}

	.session-header__counts {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-top: 12px;
	}

	.count-badge {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 10px;
		border-radius: 14px;
		font-size: 0.75rem;
		font-weight: 500;
		border: 1px solid;
	}

	.count-badge--red {
		color: var(--sc-red-text);
		background: var(--sc-red-bg);
		border-color: var(--sc-red-border);
	}

	.count-badge--green {
		color: var(--sc-green-text);
		background: var(--sc-green-bg);
		border-color: var(--sc-green-border);
	}

	.count-badge--blue {
		color: var(--sc-blue-text);
		background: var(--sc-blue-bg);
		border-color: var(--sc-blue-border);
	}

	.count-badge--grey {
		color: var(--sc-muted-text);
		background: var(--sc-grey-bg);
		border-color: var(--sc-grey-border);
	}

	.session-progress {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 16px;
		background: var(--pf-t--global--background--color--secondary--default, #f5f5f5);
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
	}

	.session-progress__text {
		white-space: nowrap;
	}

	.session-progress__bar {
		flex: 1;
		min-width: 60px;
		max-width: 200px;
	}

	.session-progress__bar-track {
		height: 4px;
		background: var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: 2px;
		overflow: hidden;
	}

	.session-progress__bar-fill {
		height: 100%;
		background: var(--pf-t--global--color--brand--default, #0066cc);
		border-radius: 2px;
		transition: width 0.3s ease;
	}

	.session-targets {
		background: var(--pf-t--global--background--color--primary--default, #fff);
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
	}

	.session-targets :global(.pf-v6-c-tabs) {
		padding: 0 var(--pf-t--global--spacer--lg, 24px);
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.target-list {
		list-style: none;
		padding: 0;
		margin: 0;
	}

	.target-list__item {
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.target-list__item:last-child {
		border-bottom: none;
	}

	.target-list__button {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 12px var(--pf-t--global--spacer--lg, 24px);
		width: 100%;
		background: none;
		border: none;
		font: inherit;
		color: inherit;
		text-align: left;
		cursor: pointer;
		transition: background-color 0.1s ease;
	}

	.target-list__button:disabled {
		cursor: default;
	}

	.target-list__button:not(:disabled):hover {
		background: var(--pf-t--global--background--color--secondary--default, #f0f0f0);
	}

	.target-list__button:focus-visible {
		outline: 2px solid var(--pf-t--global--color--brand--default, #0066cc);
		outline-offset: -2px;
	}

	.target-list__main {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		min-width: 0;
		flex: 1;
	}

	.target-list__content {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}

	.target-list__label {
		word-break: break-word;
	}

	.target-list__error {
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--color--status--danger--default, #c9190b);
		white-space: pre-wrap;
	}

	.target-list__meta {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-shrink: 0;
	}

	.target-list__time {
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
	}

	.guid-badge {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: 12px;
		font-size: 0.75rem;
		font-weight: 500;
		white-space: nowrap;
		border: 1px solid;
	}

	.guid-badge--purple {
		color: var(--sc-purple-text);
		background: var(--sc-purple-bg);
		border-color: var(--sc-purple-border);
	}

	.target-list__chevron {
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		display: inline-flex;
		align-items: center;
	}

	.session-header__rerun {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.session-header__clone-error {
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--color--status--danger--default, #c9190b);
	}

	.session-stream-notice {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px var(--pf-t--global--spacer--lg, 24px);
		background: var(--sc-gold-bg);
		border: 1px solid var(--sc-gold-border);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--sc-gold-text);
	}
</style>
