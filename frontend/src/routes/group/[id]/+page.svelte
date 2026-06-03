<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/state';
	import {
		getGroup,
		groupStream,
		runGroupChecks,
		runGroupSource,
		renameGroup,
		addGroupSource,
		removeGroupSource,
		syncGroupMetadata
	} from '$lib/api';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import GroupSourceList from '$lib/components/GroupSourceList.svelte';
	import GroupRunHistory from '$lib/components/GroupRunHistory.svelte';
	import SessionDrawer from '$lib/components/SessionDrawer.svelte';
	import type { GroupDetail } from '$lib/types';

	let data = $state.raw<GroupDetail | null>(null);
	let loading = $state(true);
	let notFound = $state(false);
	let loadError = $state('');
	let error = $state('');
	let runningAll = $state(false);
	let editingName = $state(false);
	let syncing = $state(false);
	let previewSessionId = $state<string | null>(null);
	let streamFailed = $state(false);
	let currentLoadId = 0;
	let abortController: AbortController | null = null;
	let eventSource: EventSource | null = null;
	let retryTimeout: ReturnType<typeof setTimeout> | null = null;
	let retryCount = 0;
	const MAX_RETRIES = 5;
	let pendingTimeouts: ReturnType<typeof setTimeout>[] = [];
	let rerunKnownRunIds: Set<string> | null = null;

	let groupId = $derived(page.params.id ?? '');

	function trackTimeout(fn: () => void, ms: number) {
		const id = setTimeout(fn, ms);
		pendingTimeouts.push(id);
	}

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

	function isGroupActive(detail: GroupDetail): boolean {
		return (
			detail.group.status === 'running' ||
			detail.runs.some((r) => r.status === 'running')
		);
	}

	$effect(() => {
		const _id = groupId;
		loading = true;
		notFound = false;
		loadError = '';
		error = '';
		streamFailed = false;
		retryCount = 0;
		loadGroup();
		return () => {
			closeStream();
			pendingTimeouts.forEach(clearTimeout);
			pendingTimeouts = [];
		};
	});

	onDestroy(() => {
		closeStream();
		pendingTimeouts.forEach(clearTimeout);
		pendingTimeouts = [];
	});

	async function loadGroup() {
		const myLoadId = ++currentLoadId;
		abortController?.abort();
		abortController = new AbortController();
		try {
			const result = await getGroup(groupId, { signal: abortController.signal });
			if (myLoadId !== currentLoadId) return;
			data = result;
			if (!result.group) {
				notFound = true;
			} else if (isGroupActive(result)) {
				startStreaming();
			}
		} catch (e) {
			if (myLoadId !== currentLoadId) return;
			if (e instanceof DOMException && e.name === 'AbortError') return;
			if (loading) {
				loadError = e instanceof Error ? e.message : 'Failed to load group';
			}
		}
		loading = false;
	}

	let sawActive = false;

	function startStreaming() {
		closeStream();
		retryCount = 0;
		sawActive = false;
		eventSource = groupStream(groupId);

		eventSource.onmessage = (event) => {
			try {
				const update = JSON.parse(event.data);
				data = update;

				if (rerunKnownRunIds) {
					const newRun = update.runs.find(
						(r: { run_id: string }) => !rerunKnownRunIds!.has(r.run_id)
					);
					if (newRun) {
						const sessions = update.run_sessions[newRun.run_id];
						if (sessions?.length) {
							previewSessionId = sessions[0].session_id;
							rerunKnownRunIds = null;
						}
					}
				}

				const active = isGroupActive(update);
				if (active) sawActive = true;
				if (sawActive && !active) {
					closeStream();
				}
			} catch (e) {
				console.error('Failed to parse group SSE message', e);
			}
		};

		eventSource.onerror = () => {
			eventSource?.close();
			eventSource = null;
			if (sawActive && data && !isGroupActive(data)) {
				return;
			}
			if (retryCount < MAX_RETRIES) {
				retryCount++;
				retryTimeout = setTimeout(loadGroup, 3000 * retryCount);
			} else {
				streamFailed = true;
			}
		};
	}

	async function handleRunAll() {
		runningAll = true;
		error = '';
		try {
			await runGroupChecks(groupId);
			startStreaming();
			trackTimeout(() => {
				runningAll = false;
			}, 3000);
		} catch (e) {
			runningAll = false;
			error = e instanceof Error ? e.message : 'Failed to run checks';
		}
	}

	function handleRunSource(type: string, value: string) {
		error = '';
		runGroupSource(groupId, type, value)
			.then(() => {
				startStreaming();
			})
			.catch((e) => {
				error = e instanceof Error ? e.message : 'Failed to run source check';
			});
	}

	async function handleRename(e: SubmitEvent) {
		const form = e.target as HTMLFormElement;
		const fd = new FormData(form);
		const name = ((fd.get('group_name') as string) || '').trim();
		if (!name) return;
		error = '';
		try {
			await renameGroup(groupId, name);
			editingName = false;
			await loadGroup();
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to rename group';
		}
	}

	async function addSource(type: string, value: string) {
		await addGroupSource(groupId, type, value);
		await loadGroup();
	}

	async function removeSource(type: string, value: string) {
		await removeGroupSource(groupId, type, value);
		await loadGroup();
	}

	async function handleSync() {
		syncing = true;
		error = '';
		try {
			await syncGroupMetadata(groupId);
			trackTimeout(() => {
				syncing = false;
				loadGroup();
			}, 3000);
		} catch (err) {
			syncing = false;
			error = err instanceof Error ? err.message : 'Failed to sync metadata';
		}
	}
</script>

<div class="group-page">
	<nav class="pf-v6-c-breadcrumb" aria-label="Breadcrumb">
		<ol class="pf-v6-c-breadcrumb__list">
			<li class="pf-v6-c-breadcrumb__item">
				<a class="pf-v6-c-breadcrumb__link" href="/groups">Groups</a>
			</li>
			<li class="pf-v6-c-breadcrumb__item">
				<span class="pf-v6-c-breadcrumb__item-divider">/</span>
				<span class="pf-v6-c-breadcrumb__link pf-m-current" aria-current="page">
					{data?.group?.name || 'Group'}
				</span>
			</li>
		</ol>
	</nav>

	{#if loading}
		<div role="status" aria-label="Loading group">
			<div class="group-header">
				<div class="group-header__top">
					<div class="group-header__title-group" style="flex: 1">
						<div class="pf-v6-c-skeleton pf-m-text-2xl" style="--pf-v6-c-skeleton--Width: 200px"></div>
						<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 80px; --pf-v6-c-skeleton--Height: 22px; border-radius: 12px"></div>
					</div>
				</div>
				<div class="group-header__meta">
					<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 52px; --pf-v6-c-skeleton--Height: 22px; border-radius: 12px"></div>
				</div>
			</div>
			<div class="skeleton-section">
				<div class="skeleton-section__header">
					<div class="pf-v6-c-skeleton pf-m-text-lg" style="--pf-v6-c-skeleton--Width: 100px"></div>
					<div class="skeleton-section__header-right">
						<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 90px; --pf-v6-c-skeleton--Height: 22px; border-radius: 12px"></div>
						<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 80px; --pf-v6-c-skeleton--Height: 22px; border-radius: 12px"></div>
					</div>
				</div>
			</div>
			<div class="skeleton-section">
				<div class="pf-v6-c-skeleton pf-m-text-lg" style="--pf-v6-c-skeleton--Width: 100px; margin-bottom: 12px"></div>
				{#each [280, 260, 270, 250] as w}
					<div class="skeleton-row">
						<div class="pf-v6-c-skeleton" style="--pf-v6-c-skeleton--Width: 70px; --pf-v6-c-skeleton--Height: 20px; border-radius: 10px"></div>
						<div class="pf-v6-c-skeleton pf-m-text-sm" style="--pf-v6-c-skeleton--Width: 70px"></div>
						<div class="pf-v6-c-skeleton pf-m-text-sm" style="--pf-v6-c-skeleton--Width: {w}px"></div>
					</div>
				{/each}
			</div>
		</div>
	{:else if notFound}
		<div class="pf-v6-u-text-align-center pf-v6-u-mt-2xl">
			<h2 class="pf-v6-c-title pf-m-xl">Group not found</h2>
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
			<button class="pf-v6-c-button pf-m-primary" onclick={loadGroup}>Retry</button>
		</div>
	{:else if data}
		{#if error}
		<div class="pf-v6-c-alert pf-m-danger pf-m-inline pf-v6-u-mb-md" role="alert">
			<div class="pf-v6-c-alert__icon">
				<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true"
					><path
						d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
					/></svg
				>
			</div>
			<h4 class="pf-v6-c-alert__title">{error}</h4>
		</div>
		{/if}

		{#if streamFailed}
			<div class="group-stream-notice" role="status">
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
						loadGroup();
					}}
				>
					Retry
				</button>
			</div>
		{/if}

		<div class="group-header">
			<div class="group-header__top">
				{#if editingName}
					<form
						class="group-header__rename"
						onsubmit={(e) => {
							e.preventDefault();
							handleRename(e);
						}}
					>
						<span class="pf-v6-c-form-control group-header__rename-input">
							<input name="group_name" value={data.group.name} />
						</span>
						<button class="pf-v6-c-button pf-m-primary pf-m-sm" type="submit">Save</button>
						<button
							class="pf-v6-c-button pf-m-link pf-m-sm"
							type="button"
							onclick={() => (editingName = false)}>Cancel</button
						>
					</form>
				{:else}
					<div class="group-header__title-group">
						<h1 class="pf-v6-c-title pf-m-2xl">
							{data.group.name || 'Unnamed Group'}
						</h1>
						<StatusBadge status={data.group.status} />
						<button
							class="pf-v6-c-button pf-m-plain pf-m-sm"
							onclick={() => {
								editingName = true;
							}}
							aria-label="Edit name"
						>
							<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
								><path
									d="M12.146 1.146a.5.5 0 0 1 .708 0l2 2a.5.5 0 0 1 0 .708l-9.5 9.5a.5.5 0 0 1-.233.131l-3 1a.5.5 0 0 1-.632-.632l1-3a.5.5 0 0 1 .131-.233l9.5-9.5ZM11.207 4L12 3.207 12.793 4 12 4.793 11.207 4Zm-.414 1.414L3.5 12.707l-.293.879.879-.293L11.379 6 10.793 5.414Z"
								/></svg
							>
						</button>
					</div>
				{/if}
			</div>

			<div class="group-header__meta">
				{#if data.group.babylon_cluster}
					<span class="pf-v6-c-label pf-m-compact"
						><span class="pf-v6-c-label__content"
							><span class="pf-v6-c-label__text">{data.group.babylon_cluster}</span></span
						></span
					>
				{/if}
			</div>
		</div>

		<GroupSourceList
			group={data.group}
			runs={data.runs}
			runSessions={data.run_sessions}
			{syncing}
			{runningAll}
			onRunAll={handleRunAll}
			onRunSource={handleRunSource}
			onAddSource={addSource}
			onRemoveSource={removeSource}
			onSync={handleSync}
			onError={(msg) => {
				error = msg;
			}}
		/>

		<GroupRunHistory
			runs={data.runs}
			runSessions={data.run_sessions}
			targetsBySession={data.targets_by_session}
			onPreview={(id) => {
				previewSessionId = id;
			}}
		/>

		{#if previewSessionId}
			<SessionDrawer
				sessionId={previewSessionId}
				onClose={() => (previewSessionId = null)}
				onRerun={(type, value) => {
					rerunKnownRunIds = new Set(data?.runs.map((r) => r.run_id) ?? []);
					handleRunSource(type, value);
				}}
			/>
		{/if}
	{/if}
</div>

<style>
	.skeleton-section {
		padding: var(--pf-t--global--spacer--lg, 24px);
		background: var(--pf-t--global--background--color--primary--default, #fff);
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
	}

	.skeleton-section__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.skeleton-section__header-right {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.skeleton-row {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 0;
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.skeleton-row:last-child {
		border-bottom: none;
	}

	.group-header {
		padding: var(--pf-t--global--spacer--lg, 24px);
		background: var(--pf-t--global--background--color--primary--default, #fff);
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		margin-top: var(--pf-t--global--spacer--md, 16px);
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
	}

	.group-header__top {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 16px;
	}

	.group-header__title-group {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		min-width: 0;
	}

	.group-header__title-group h1 {
		margin: 0;
		word-break: break-word;
	}

	.group-header__rename {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
	}

	.group-header__rename-input {
		flex: 1;
	}

	.group-header__meta {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-top: 12px;
		padding-top: 12px;
		border-top: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.group-stream-notice {
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
