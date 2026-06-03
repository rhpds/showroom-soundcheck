<script lang="ts">
	import type { MultiWorkshopDashboardItem, WorkshopDashboardItem, WorkshopCheckStatusMap } from '$lib/types';
	import { workshopStatusLabel } from '$lib/utils';
	import { checkStatusLabel } from '$lib/checkStatuses.svelte';

	type TimelineRow =
		| { kind: 'workshop'; item: WorkshopDashboardItem; startMs: number; endMs: number }
		| { kind: 'multi'; item: MultiWorkshopDashboardItem; startMs: number; endMs: number }
		| { kind: 'child'; item: WorkshopDashboardItem; parentName: string; startMs: number; endMs: number };

	let {
		row,
		x,
		y,
		checkStatuses = {}
	}: {
		row: TimelineRow;
		x: number;
		y: number;
		checkStatuses?: WorkshopCheckStatusMap;
	} = $props();

	function fmtDateTime(iso: string): string {
		if (!iso) return '—';
		const d = new Date(iso);
		if (isNaN(d.getTime())) return '—';
		return d.toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}
</script>

<div class="timeline-tooltip" style="left: {x}px; top: {y}px;" role="tooltip">
	{#if row.kind === 'multi'}
		<strong class="tooltip-name">{row.item.display_name}</strong>
		{#if row.item.requester}
			<span>User: {row.item.requester}{#if row.item.ordered_by && row.item.ordered_by !== row.item.requester} (by {row.item.ordered_by}){/if}</span>
		{:else if row.item.ordered_by}
			<span>Ordered by: {row.item.ordered_by}</span>
		{/if}
		<span>Start: {fmtDateTime(row.item.start_date)}</span>
		<span>End: {fmtDateTime(row.item.end_date)}</span>
		<span>Event &middot; {row.item.children.length} workshops</span>
		<span>Cluster: {row.item.cluster}</span>
		<span>Status: {workshopStatusLabel(row.item.status)}</span>
		<span>Seats: {row.item.number_seats}</span>
		<span>Instances: {row.item.provision_active}/{row.item.provision_ordered}</span>
		{#if row.item.provision_failed > 0}
			<span class="tooltip-failed">Failed: {row.item.provision_failed}</span>
		{/if}
		{#if row.item.users_total > 0}
			<span>Users: {row.item.users_assigned}/{row.item.users_total}</span>
		{/if}
		{#if row.item.purpose}
			<span>Purpose: {row.item.purpose}</span>
		{/if}
	{:else}
		{@const ws = row.item}
		<strong class="tooltip-name">{ws.display_name}</strong>
		{#if ws.requester}
			<span>User: {ws.requester}{#if ws.ordered_by && ws.ordered_by !== ws.requester} (by {ws.ordered_by}){/if}</span>
		{:else if ws.ordered_by}
			<span>Ordered by: {ws.ordered_by}</span>
		{/if}
		{#if ws.catalog_item}
			<span>Catalog: {ws.catalog_item}</span>
		{/if}
		<span>Start: {fmtDateTime(ws.lifespan_start)}</span>
		<span>End: {fmtDateTime(ws.lifespan_end)}</span>
		<span>Cluster: {ws.cluster}</span>
		<span>Status: {workshopStatusLabel(ws.status)}</span>
		<span>Instances: {ws.provision_active}/{ws.provision_ordered}</span>
		{#if ws.provision_failed > 0}
			<span class="tooltip-failed">Failed: {ws.provision_failed}</span>
		{/if}
		<span>Users: {ws.users_assigned}/{ws.users_total}</span>
		{#if ws.white_glove}<span class="tooltip-wg">White-glove</span>{/if}
		{#if ws.demo_team_provisioned}<span class="tooltip-dt">Demo team</span>{/if}
		{#if ws.locked}<span class="tooltip-locked">Locked</span>{/if}
		{#if ws.disable_auto_stop}<span class="tooltip-no-autostop">No auto-stop</span>{/if}
		{#if ws.workshop_id}
			{@const cs = checkStatuses[ws.workshop_id]}
			<span class="tooltip-check-row">
				Check: {cs ? checkStatusLabel(cs.status) : '—'}
			</span>
		{/if}
	{/if}
</div>

<style>
	.timeline-tooltip {
		position: fixed;
		transform: translate(-50%, -100%);
		margin-top: -12px;
		pointer-events: none;
		background: #1b1d21;
		color: #fff;
		padding: 8px 12px;
		border-radius: 6px;
		font-size: 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 2px;
		max-width: 320px;
		word-break: break-word;
		z-index: 100;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
	}

	.tooltip-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 280px;
	}

	.tooltip-failed {
		color: #f4a460;
		font-weight: 600;
	}

	.tooltip-wg {
		color: #f0c75e;
	}

	.tooltip-dt {
		color: #c8a0d8;
	}

	.tooltip-locked {
		color: #73bcf7;
	}

	.tooltip-no-autostop {
		color: #f4a460;
	}

	.tooltip-check-row {
		margin-top: 2px;
		padding-top: 3px;
		border-top: 1px solid rgba(255, 255, 255, 0.15);
		color: #73bcf7;
	}
</style>
