<script lang="ts">
	import { goto } from '$app/navigation';
	import { listSessions, deleteSession, toggleSessionPin } from '$lib/api';
	import { relativeTime } from '$lib/utils';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import type { SessionListItem, PaginatedResponse } from '$lib/types';

	let { data: pageData } = $props();

	let data = $state.raw<PaginatedResponse<SessionListItem>>(pageData.sessions);
	let loading = $state(false);
	let error = $state('');

	let page = $state(pageData.initialPage);
	let perPage = $state(pageData.initialPerPage);
	let search = $state(pageData.initialSearch);
	let searchInput = $state(pageData.initialSearch);

	$effect(() => {
		data = pageData.sessions;
	});

	async function loadData() {
		loading = true;
		error = '';
		try {
			data = await listSessions({
				page,
				per_page: perPage,
				search: search || undefined
			});
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load sessions';
		}
		loading = false;
	}

	function handleSearch() {
		search = searchInput;
		page = 1;
		loadData();
	}

	function handleClearSearch() {
		searchInput = '';
		search = '';
		page = 1;
		loadData();
	}

	function goToPage(p: number) {
		page = p;
		loadData();
	}

	function handlePerPageChange(e: Event) {
		perPage = parseInt((e.target as HTMLSelectElement).value);
		page = 1;
		loadData();
	}

	async function handlePin(e: Event, session: SessionListItem) {
		e.stopPropagation();
		try {
			const result = await toggleSessionPin(session.session_id);
			data = {
				...data,
				items: data.items.map((s) =>
					s.session_id === session.session_id ? { ...s, pinned: result.pinned } : s
				)
			};
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to toggle pin';
		}
	}

	async function handleDelete(e: Event, session: SessionListItem) {
		e.stopPropagation();
		const label =
			session.resource_display_name || session.name || session.display_label || 'this session';
		if (!confirm(`Delete "${label}"?`)) return;
		try {
			await deleteSession(session.session_id);
			await loadData();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to delete session';
		}
	}

	let totalPages = $derived(Math.ceil(data.total / data.per_page));
</script>

<div class="page-header">
	<h1 class="pf-v6-c-title pf-m-2xl">Sessions</h1>
	<div class="page-header__actions">
		<div class="pf-v6-c-input-group header-search">
			<div class="pf-v6-c-input-group__item pf-m-fill">
				<span class="pf-v6-c-form-control">
					<input
						type="search"
						placeholder="Search sessions..."
						aria-label="Search sessions"
						bind:value={searchInput}
						onkeydown={(e) => {
							if (e.key === 'Enter') handleSearch();
						}}
					/>
				</span>
			</div>
			<div class="pf-v6-c-input-group__item">
				<button class="pf-v6-c-button pf-m-control" aria-label="Search" onclick={handleSearch}>
					<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
						<path
							d="M11.5 10.4l3.8 3.8-.7.7-3.8-3.8a6 6 0 1 1 .7-.7zM6.5 11A4.5 4.5 0 1 0 6.5 2a4.5 4.5 0 0 0 0 9z"
						/>
					</svg>
				</button>
			</div>
			{#if search}
				<div class="pf-v6-c-input-group__item">
					<button
						class="pf-v6-c-button pf-m-plain"
						aria-label="Clear search"
						onclick={handleClearSearch}
					>
						<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
							<path d="M12.5 3.5L8 8l4.5 4.5-1 1L7 9l-4.5 4.5-1-1L6 8 1.5 3.5l1-1L7 7l4.5-4.5z" />
						</svg>
					</button>
				</div>
			{/if}
		</div>
		<a href="/sessions/new" class="pf-v6-c-button pf-m-primary create-btn">
			<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
				<path
					d="M8 2a.5.5 0 0 1 .5.5V7H13a.5.5 0 0 1 0 1H8.5v4.5a.5.5 0 0 1-1 0V8H3a.5.5 0 0 1 0-1h4.5V2.5A.5.5 0 0 1 8 2z"
				/>
			</svg>
			<span class="create-btn__label">Create session</span>
		</a>
	</div>
</div>

{#if loading}
	<TableSkeleton headers={['Name', 'Status', 'Source', 'Created']} />
{:else if error}
	<div class="pf-v6-c-alert pf-m-danger pf-m-inline" role="alert">
		<div class="pf-v6-c-alert__icon">
			<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true"
				><path
					d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
				/></svg
			>
		</div>
		<p class="pf-v6-c-alert__title">{error}</p>
	</div>
{:else if data.items.length === 0}
	<div class="pf-v6-c-empty-state">
		<div class="pf-v6-c-empty-state__content">
			<h2 class="pf-v6-c-empty-state__title-text">No sessions found</h2>
			<div class="pf-v6-c-empty-state__body">
				{#if search}
					No sessions match your search.
				{:else}
					Get started by creating a new session.
				{/if}
			</div>
			<div class="pf-v6-c-empty-state__actions">
				{#if search}
					<button
						class="pf-v6-c-button pf-m-link"
						onclick={() => {
							search = '';
							searchInput = '';
							page = 1;
							loadData();
						}}
					>
						Clear search
					</button>
				{:else}
					<a href="/sessions/new" class="pf-v6-c-button pf-m-primary">Create new session</a>
				{/if}
			</div>
		</div>
	</div>
{:else}
	<table class="pf-v6-c-table pf-m-grid-md" role="grid" data-sveltekit-preload-data="hover">
		<thead class="pf-v6-c-table__thead">
			<tr class="pf-v6-c-table__tr">
				<th class="pf-v6-c-table__th col-pin" aria-label="Pin"></th>
				<th class="pf-v6-c-table__th">Name</th>
				<th class="pf-v6-c-table__th">Status</th>
				<th class="pf-v6-c-table__th">Source</th>
				<th class="pf-v6-c-table__th">Created</th>
				<th class="pf-v6-c-table__th col-actions" aria-label="Actions"></th>
			</tr>
		</thead>
		<tbody class="pf-v6-c-table__tbody">
			{#each data.items as session}
				<tr
					class="pf-v6-c-table__tr pf-m-clickable"
					onclick={() => {
						goto(`/session/${session.session_id}`);
					}}
				>
					<td class="pf-v6-c-table__td col-pin" data-label="Pin">
						<button
							class="pf-v6-c-button pf-m-plain pin-btn"
							class:pinned={session.pinned}
							aria-label={session.pinned ? 'Unpin' : 'Pin'}
							title={session.pinned ? 'Unpin' : 'Pin to top'}
							onclick={(e) => handlePin(e, session)}
						>
							<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"
								><path
									d="M9.828.722a.5.5 0 0 1 .354.146l4.95 4.95a.5.5 0 0 1-.707.707l-.71-.71-3.18 3.18a5.5 5.5 0 0 1-1.32 4.988.5.5 0 0 1-.707 0L5.57 11.045l-3.863 3.863a.5.5 0 1 1-.707-.708l3.863-3.862L1.93 7.4a.5.5 0 0 1 0-.708 5.5 5.5 0 0 1 4.988-1.32L10.1 2.19l-.71-.71a.5.5 0 0 1 .44-.858Z"
								/></svg
							>
						</button>
					</td>
					<td class="pf-v6-c-table__td" data-label="Name">
						<a href="/session/{session.session_id}" class="session-link">
							{#if session.resource_display_name && session.source_id}
								{session.resource_display_name} - {session.source_id}
							{:else}
								{session.resource_display_name ||
									session.name ||
									session.display_label ||
									'Unnamed'}
							{/if}
						</a>
						{#if session.group_id}
							<a
								href="/group/{session.group_id}"
								class="group-badge"
								title="Part of a group"
								onclick={(e) => e.stopPropagation()}
							>
								<svg
									viewBox="0 0 16 16"
									width="11"
									height="11"
									fill="currentColor"
									aria-hidden="true"
									><path
										d="M1 3.5A1.5 1.5 0 0 1 2.5 2h3.879a1.5 1.5 0 0 1 1.06.44l1.122 1.12H13.5A1.5 1.5 0 0 1 15 5v7.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 1 12.5v-9ZM2.5 3a.5.5 0 0 0-.5.5v9a.5.5 0 0 0 .5.5h11a.5.5 0 0 0 .5-.5V5a.5.5 0 0 0-.5-.5H8.561a.5.5 0 0 1-.354-.146L7.086 3.232A.5.5 0 0 0 6.732 3H2.5Z"
									/></svg
								>
								Group
							</a>
						{/if}
					</td>
					<td class="pf-v6-c-table__td" data-label="Status">
						<StatusBadge status={session.status} size="sm" />
					</td>
					<td class="pf-v6-c-table__td" data-label="Source">
						<span class="source-label">{session.display_label}</span>
					</td>
					<td class="pf-v6-c-table__td" data-label="Created">
						{relativeTime(session.created_at)}
					</td>
					<td class="pf-v6-c-table__td col-actions" data-label="Actions">
						<button
							class="pf-v6-c-button pf-m-plain delete-btn"
							aria-label="Delete session"
							title="Delete"
							onclick={(e) => handleDelete(e, session)}
						>
							<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"
								><path
									d="M5.5 5.5a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Z"
								/><path
									d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1 0-2H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1ZM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118ZM7 1.5a.5.5 0 0 0-.5.5h3a.5.5 0 0 0-.5-.5H7Z"
								/></svg
							>
						</button>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>

	{#if totalPages > 1}
		<div class="pagination">
			<div class="pagination-controls">
				<span class="pf-v6-c-form-control per-page-select">
					<select aria-label="Items per page" onchange={handlePerPageChange}>
						{#each [10, 20, 50, 100] as size}
							<option value={size} selected={perPage === size}>{size} per page</option>
						{/each}
					</select>
				</span>

				<span class="pagination-info">
					{(page - 1) * perPage + 1}–{Math.min(page * perPage, data.total)} of {data.total}
				</span>

				<div class="pagination-nav">
					<button
						class="pf-v6-c-button pf-m-plain"
						aria-label="First page"
						disabled={page === 1}
						onclick={() => goToPage(1)}
					>
						<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
							><path d="M11 2L5 8l6 6V2z" /><path d="M5 2H3v12h2V2z" /></svg
						>
					</button>
					<button
						class="pf-v6-c-button pf-m-plain"
						aria-label="Previous page"
						disabled={page === 1}
						onclick={() => goToPage(page - 1)}
					>
						<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
							><path d="M10 2L4 8l6 6V2z" /></svg
						>
					</button>
					<span class="page-number">Page {page} of {totalPages}</span>
					<button
						class="pf-v6-c-button pf-m-plain"
						aria-label="Next page"
						disabled={page === totalPages}
						onclick={() => goToPage(page + 1)}
					>
						<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
							><path d="M6 2l6 6-6 6V2z" /></svg
						>
					</button>
					<button
						class="pf-v6-c-button pf-m-plain"
						aria-label="Last page"
						disabled={page === totalPages}
						onclick={() => goToPage(totalPages)}
					>
						<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
							><path d="M5 2l6 6-6 6V2z" /><path d="M11 2h2v12h-2V2z" /></svg
						>
					</button>
				</div>
			</div>
		</div>
	{/if}
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

	.create-btn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
		padding-inline: var(--pf-t--global--spacer--md, 16px);
		white-space: nowrap;
	}

	.header-search {
		display: flex;
		align-items: stretch;
		min-width: 140px;
		max-width: 280px;
	}

	@media (max-width: 768px) {
		.page-header {
			flex-direction: column;
			align-items: flex-start;
		}

		.page-header__actions {
			width: 100%;
		}

		.header-search {
			flex: 1;
			min-width: 0;
		}

		.create-btn__label {
			display: none;
		}
	}

	.header-search .pf-v6-c-input-group__item {
		display: flex;
		align-items: stretch;
	}

	.header-search .pf-v6-c-button {
		align-self: stretch;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}

	.header-search .pf-v6-c-button svg {
		width: 16px;
		height: 16px;
	}

	.pf-v6-c-input-group__item.pf-m-fill {
		flex: 1;
	}

	.pf-v6-c-table .pf-m-clickable {
		cursor: pointer;
	}

	.pf-v6-c-table .pf-m-clickable:hover {
		background-color: var(--pf-t--global--background--color--secondary--hover, #f0f0f0);
	}

	.session-link {
		color: var(--pf-t--global--color--link--default, #0066cc);
		text-decoration: none;
		font-weight: 500;
	}

	.session-link:hover {
		text-decoration: underline;
	}

	.source-label {
		font-size: 0.85rem;
		opacity: 0.75;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 250px;
		display: inline-block;
	}

	.pagination {
		margin-top: var(--pf-t--global--spacer--md, 16px);
		padding-top: var(--pf-t--global--spacer--md, 16px);
		border-top: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.pagination-controls {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--pf-t--global--spacer--md, 16px);
		flex-wrap: wrap;
	}

	.pagination-info {
		font-size: 0.875rem;
	}

	.pagination-nav {
		display: flex;
		align-items: center;
		gap: 4px;
	}

	.page-number {
		font-size: 0.875rem;
		padding: 0 8px;
	}

	.per-page-select {
		width: auto;
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

	.group-badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		margin-left: 8px;
		padding: 1px 8px;
		border-radius: 10px;
		font-size: 0.7rem;
		font-weight: 500;
		color: #005f60;
		background: #e0f5f5;
		border: 1px solid #7ecbc0;
		text-decoration: none;
		vertical-align: middle;
	}

	.group-badge:hover {
		text-decoration: underline;
	}

	.col-pin,
	.col-actions {
		width: 40px;
		text-align: center;
		padding: 8px 4px !important;
	}

	.pin-btn {
		opacity: 0.25;
		transition: opacity 0.15s;
	}

	.pin-btn:hover,
	.pin-btn.pinned {
		opacity: 1;
	}

	.pin-btn.pinned {
		color: var(--pf-t--global--color--brand--default, #0066cc);
	}

	.delete-btn {
		opacity: 0.3;
		transition: opacity 0.15s;
	}

	.delete-btn:hover {
		opacity: 1;
		color: var(--pf-t--global--color--status--danger--default, #c9190b);
	}
</style>
