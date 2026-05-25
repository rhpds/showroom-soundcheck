<script lang="ts">
	import { goto } from '$app/navigation';
	import { listGroups, deleteGroup, toggleGroupPin } from '$lib/api';
	import { relativeTime } from '$lib/utils';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import type { GroupListItem, PaginatedResponse } from '$lib/types';

	let { data: pageData } = $props();

	let data = $state.raw<PaginatedResponse<GroupListItem>>(pageData.initialData);
	let loading = $state(false);
	let error = $state('');

	$effect.pre(() => {
		data = pageData.initialData;
	});

	let page = $state(1);
	let perPage = $state(20);
	let search = $state('');
	let searchInput = $state('');

	async function loadData() {
		loading = true;
		error = '';
		try {
			data = await listGroups({
				page,
				per_page: perPage,
				search: search || undefined
			});
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load groups';
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

	async function handlePin(e: Event, group: GroupListItem) {
		e.stopPropagation();
		try {
			const result = await toggleGroupPin(group.group_id);
			group.pinned = result.pinned;
			await loadData();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to toggle pin';
		}
	}

	async function handleDelete(e: Event, group: GroupListItem) {
		e.stopPropagation();
		const label = group.name || 'this group';
		if (!confirm(`Delete "${label}" and all its runs/sessions?`)) return;
		try {
			await deleteGroup(group.group_id);
			await loadData();
		} catch (err: unknown) {
			error = err instanceof Error ? err.message : 'Failed to delete group';
		}
	}

	let totalPages = $derived(Math.ceil(data.total / data.per_page));
</script>

<div class="page-header">
	<h1 class="pf-v6-c-title pf-m-2xl">Groups</h1>
	<div class="page-header__actions">
		<div class="pf-v6-c-input-group header-search">
			<div class="pf-v6-c-input-group__item pf-m-fill">
				<span class="pf-v6-c-form-control">
					<input
						type="search"
						placeholder="Search groups..."
						aria-label="Search groups"
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
		<a href="/groups/new" class="pf-v6-c-button pf-m-primary create-btn">
			<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
				<path d="M8 2a.5.5 0 0 1 .5.5V7H13a.5.5 0 0 1 0 1H8.5v4.5a.5.5 0 0 1-1 0V8H3a.5.5 0 0 1 0-1h4.5V2.5A.5.5 0 0 1 8 2z" />
			</svg>
			<span class="create-btn__label">Create group</span>
		</a>
	</div>
</div>

{#if loading}
	<div class="pf-v6-u-text-align-center pf-v6-u-p-xl">
		<Spinner label="Loading groups" />
	</div>
{:else if error}
	<div class="pf-v6-c-alert pf-m-danger pf-m-inline">
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
			<h2 class="pf-v6-c-empty-state__title-text">No groups found</h2>
			<div class="pf-v6-c-empty-state__body">
				{#if search}
					No groups match your search.
				{:else}
					Get started by creating a new group.
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
					<a href="/groups/new" class="pf-v6-c-button pf-m-primary">Create new group</a>
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
				<th class="pf-v6-c-table__th">Sources</th>
				<th class="pf-v6-c-table__th">Created</th>
				<th class="pf-v6-c-table__th col-actions" aria-label="Actions"></th>
			</tr>
		</thead>
		<tbody class="pf-v6-c-table__tbody">
			{#each data.items as group}
				<tr
					class="pf-v6-c-table__tr pf-m-clickable"
					onclick={() => {
						goto(`/group/${group.group_id}`);
					}}
				>
					<td class="pf-v6-c-table__td col-pin" data-label="Pin">
						<button
							class="pf-v6-c-button pf-m-plain pin-btn"
							class:pinned={group.pinned}
							aria-label={group.pinned ? 'Unpin' : 'Pin'}
							title={group.pinned ? 'Unpin' : 'Pin to top'}
							onclick={(e) => handlePin(e, group)}
						>
							<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M9.828.722a.5.5 0 0 1 .354.146l4.95 4.95a.5.5 0 0 1-.707.707l-.71-.71-3.18 3.18a5.5 5.5 0 0 1-1.32 4.988.5.5 0 0 1-.707 0L5.57 11.045l-3.863 3.863a.5.5 0 1 1-.707-.708l3.863-3.862L1.93 7.4a.5.5 0 0 1 0-.708 5.5 5.5 0 0 1 4.988-1.32L10.1 2.19l-.71-.71a.5.5 0 0 1 .44-.858Z"/></svg>
						</button>
					</td>
					<td class="pf-v6-c-table__td" data-label="Name">
						<a href="/group/{group.group_id}" class="group-link">
							{group.name || 'Unnamed Group'}
						</a>
					</td>
					<td class="pf-v6-c-table__td" data-label="Status">
						<StatusBadge status={group.status} size="sm" />
					</td>
					<td class="pf-v6-c-table__td" data-label="Sources">
						{group.source_count} source{group.source_count !== 1 ? 's' : ''}
					</td>
					<td class="pf-v6-c-table__td" data-label="Created">
						{relativeTime(group.created_at)}
					</td>
					<td class="pf-v6-c-table__td col-actions" data-label="Actions">
						<button
							class="pf-v6-c-button pf-m-plain delete-btn"
							aria-label="Delete group"
							title="Delete"
							onclick={(e) => handleDelete(e, group)}
						>
							<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true"><path d="M5.5 5.5a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Z"/><path d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1 0-2H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1ZM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118ZM7 1.5a.5.5 0 0 0-.5.5h3a.5.5 0 0 0-.5-.5H7Z"/></svg>
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

	.group-link {
		color: var(--pf-t--global--color--link--default, #0066cc);
		text-decoration: none;
		font-weight: 500;
	}

	.group-link:hover {
		text-decoration: underline;
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
