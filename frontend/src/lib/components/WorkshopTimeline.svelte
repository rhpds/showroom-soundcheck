<script lang="ts">
	import { onMount } from 'svelte';
	import type { MultiWorkshopDashboardItem, WorkshopDashboardItem, WorkshopStatus, WorkshopCheckStatusMap } from '$lib/types';
	import { workshopStatusBg, workshopStatusTextColor, workshopStatusLabel } from '$lib/utils';

	let {
		items,
		multiWorkshops = [],
		filterFrom,
		filterTo,
		timeWindow,
		checkStatuses = {},
		onRunCheck
	}: {
		items: WorkshopDashboardItem[];
		multiWorkshops?: MultiWorkshopDashboardItem[];
		filterFrom?: string;
		filterTo?: string;
		timeWindow?: 'all' | 'today' | '24h' | 'week';
		checkStatuses?: WorkshopCheckStatusMap;
		onRunCheck?: (workshopId: string, cluster: string, displayName: string) => void;
	} = $props();

	let containerWidth = $state(800);
	let container: HTMLDivElement;

	onMount(() => {
		const observer = new ResizeObserver((entries) => {
			for (const entry of entries) {
				containerWidth = entry.contentRect.width;
			}
		});
		observer.observe(container);
		return () => observer.disconnect();
	});

	const ROW_HEIGHT = 36;
	const ROW_GAP = 4;
	const LABEL_WIDTH = 220;
	const PADDING_TOP = 40;
	const HEADER_HEIGHT = 30;

	const MWS_ROW_HEIGHT = 42;

	type TimelineRow =
		| { kind: 'workshop'; item: WorkshopDashboardItem; startMs: number; endMs: number }
		| { kind: 'multi'; item: MultiWorkshopDashboardItem; startMs: number; endMs: number };

	let timelineItems = $derived.by(() => {
		const now = Date.now();
		const rows: TimelineRow[] = [];

		for (const mws of multiWorkshops) {
			const startMs = mws.start_date ? new Date(mws.start_date).getTime() : now;
			let endMs = mws.end_date ? new Date(mws.end_date).getTime() : now + 4 * 3600000;
			if (endMs <= startMs) endMs = startMs + 3600000;
			if (!isNaN(startMs) && !isNaN(endMs)) {
				rows.push({ kind: 'multi', item: mws, startMs, endMs });
			}
		}

		for (const item of items) {
			const startMs = item.lifespan_start ? new Date(item.lifespan_start).getTime() : now;
			let endMs = item.lifespan_end ? new Date(item.lifespan_end).getTime() : now + 4 * 3600000;
			if (endMs <= startMs) endMs = startMs + 3600000;
			if (!isNaN(startMs) && !isNaN(endMs)) {
				rows.push({ kind: 'workshop', item, startMs, endMs });
			}
		}

		return rows.sort((a, b) => a.startMs - b.startMs);
	});

	function floorToHourWithGrace(now: number): number {
		const grace = 15 * 60 * 1000;
		const adjusted = now - grace;
		const d = new Date(adjusted);
		d.setMinutes(0, 0, 0);
		return d.getTime();
	}

	function floorToDay(ms: number): number {
		const d = new Date(ms);
		d.setHours(0, 0, 0, 0);
		return d.getTime();
	}

	let timeRange = $derived.by(() => {
		const now = Date.now();

		if (timeWindow === '24h') {
			const start = floorToHourWithGrace(now);
			const end = start + 27 * 3600000;
			return { minMs: start, maxMs: end };
		}

		if (timeWindow === 'today') {
			const start = floorToDay(now);
			const end = start + 24 * 3600000;
			return { minMs: start, maxMs: end };
		}

		if (timeWindow === 'week') {
			const start = floorToDay(now);
			const end = start + 7 * 24 * 3600000;
			return { minMs: start, maxMs: end };
		}

		if (filterFrom && filterTo) {
			const filterMinMs = new Date(filterFrom).getTime();
			const filterMaxMs = new Date(filterTo).getTime();
			const padding = (filterMaxMs - filterMinMs) * 0.02 || 3600000;
			return { minMs: filterMinMs - padding, maxMs: filterMaxMs + padding };
		}

		if (timelineItems.length === 0) {
			return { minMs: now, maxMs: now + 24 * 3600000 };
		}
		let minMs = Infinity;
		let maxMs = -Infinity;
		for (const t of timelineItems) {
			if (t.startMs < minMs) minMs = t.startMs;
			if (t.endMs > maxMs) maxMs = t.endMs;
		}
		const padding = (maxMs - minMs) * 0.05 || 3600000;
		return { minMs: minMs - padding, maxMs: maxMs + padding };
	});

	let chartWidth = $derived(Math.max(containerWidth - LABEL_WIDTH - 20, 200));
	let svgHeight = $derived(
		PADDING_TOP + HEADER_HEIGHT + timelineItems.length * (ROW_HEIGHT + ROW_GAP) + 20
	);

	function msToX(ms: number): number {
		const range = timeRange.maxMs - timeRange.minMs;
		if (range === 0) return 0;
		return ((ms - timeRange.minMs) / range) * chartWidth;
	}

	let nowX = $derived(msToX(Date.now()));

	function formatTickLabel(ms: number, mode: string): string {
		const d = new Date(ms);
		if (mode === 'week') {
			return d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
		}
		return d.toLocaleString(undefined, { hour: '2-digit', minute: '2-digit' });
	}

	let ticks = $derived.by(() => {
		let intervalMs: number;
		let mode: string;

		if (timeWindow === '24h') {
			intervalMs = 3 * 3600000;
			mode = 'hours';
		} else if (timeWindow === 'today') {
			intervalMs = 3 * 3600000;
			mode = 'hours';
		} else if (timeWindow === 'week') {
			intervalMs = 24 * 3600000;
			mode = 'week';
		} else {
			const range = timeRange.maxMs - timeRange.minMs;
			if (range <= 2 * 24 * 3600000) {
				intervalMs = 3 * 3600000;
				mode = 'hours';
			} else if (range <= 14 * 24 * 3600000) {
				intervalMs = 24 * 3600000;
				mode = 'week';
			} else {
				intervalMs = 7 * 24 * 3600000;
				mode = 'week';
			}
		}

		const result: { ms: number; x: number; label: string }[] = [];
		let tick = timeRange.minMs;
		while (tick <= timeRange.maxMs) {
			result.push({ ms: tick, x: msToX(tick), label: formatTickLabel(tick, mode) });
			tick += intervalMs;
		}
		return result;
	});

	let hoveredIndex = $state<number | null>(null);
	let tooltipX = $state(0);
	let tooltipY = $state(0);

	function handleBarEnter(idx: number, e: MouseEvent) {
		hoveredIndex = idx;
		tooltipX = e.clientX;
		tooltipY = e.clientY;
	}

	function handleBarMove(e: MouseEvent) {
		tooltipX = e.clientX;
		tooltipY = e.clientY;
	}

	function handleBarFocus(idx: number) {
		hoveredIndex = idx;
		const bar = container.querySelector(`[data-bar-idx="${idx}"]`) as SVGElement | null;
		if (bar) {
			const rect = bar.getBoundingClientRect();
			tooltipX = rect.left + rect.width / 2;
			tooltipY = rect.top;
		}
	}

	function barAriaLabel(tRow: TimelineRow): string {
		if (tRow.kind === 'multi') {
			const m = tRow.item;
			return `${m.display_name}: Event, ${m.children.length} workshops, ${m.number_seats} seats, ${workshopStatusLabel(m.status)}`;
		}
		const i = tRow.item;
		let label = `${i.display_name}: ${workshopStatusLabel(i.status)}, ${i.provision_active}/${i.provision_ordered} instances`;
		if (i.users_total > 0) label += `, ${i.users_assigned}/${i.users_total} users`;
		if (i.provision_failed > 0) label += `, ${i.provision_failed} failed`;
		if (i.white_glove) label += ', white-glove';
		if (i.locked) label += ', locked';
		if (i.disable_auto_stop) label += ', no auto-stop';
		return label;
	}


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

	function checkLabel(status: string): string {
		switch (status) {
			case 'completed': return 'Passed';
			case 'running': return 'Running';
			case 'pending': return 'Pending';
			case 'failed': return 'Failed';
			default: return status;
		}
	}
</script>

<div class="timeline-container" bind:this={container}>
	{#if timelineItems.length === 0}
		<div class="timeline-empty">No workshops with schedule data to display.</div>
	{:else}
		<div class="timeline-scroll">
			<svg
				width={LABEL_WIDTH + chartWidth + 20}
				height={svgHeight}
				class="timeline-svg"
				role="img"
				aria-label="Workshop timeline chart showing {timelineItems.length} workshops"
			>
				<!-- Time axis ticks -->
				{#each ticks as tick}
					<line
						x1={LABEL_WIDTH + tick.x}
						y1={PADDING_TOP}
						x2={LABEL_WIDTH + tick.x}
						y2={svgHeight - 10}
						stroke="#e0e0e0"
						stroke-width="1"
						stroke-dasharray="4 2"
					/>
					<text
						x={LABEL_WIDTH + tick.x}
						y={PADDING_TOP - 8}
						text-anchor="middle"
						font-size="10"
						fill="#6a6a6a"
					>
						{tick.label}
					</text>
				{/each}

				<!-- Now line -->
				{#if nowX >= 0 && nowX <= chartWidth}
					<line
						x1={LABEL_WIDTH + nowX}
						y1={PADDING_TOP}
						x2={LABEL_WIDTH + nowX}
						y2={svgHeight - 10}
						stroke="#c9190b"
						stroke-width="1.5"
						stroke-dasharray="6 3"
					/>
					<text
						x={LABEL_WIDTH + nowX}
						y={PADDING_TOP - 18}
						text-anchor="middle"
						font-size="9"
						fill="#c9190b"
						font-weight="600"
					>
						NOW
					</text>
				{/if}

				<!-- Workshop bars -->
			{#each timelineItems as tRow, idx}
				{@const y = PADDING_TOP + HEADER_HEIGHT + idx * (ROW_HEIGHT + ROW_GAP)}
				{@const rawBarX = msToX(tRow.startMs)}
				{@const rawBarEnd = msToX(tRow.endMs)}
				{@const barX = Math.max(rawBarX, 0)}
				{@const barWidth = Math.max(Math.min(rawBarEnd, chartWidth) - barX, 4)}

				{#if tRow.kind === 'multi'}
					{@const mws = tRow.item}
				<!-- MultiWorkshop label -->
				<foreignObject x="0" y={y} width={LABEL_WIDTH} height={MWS_ROW_HEIGHT}>
					<div class="tl-label-row">
						{#if mws.catalog_url}
							<a href={mws.catalog_url} target="_blank" rel="noopener noreferrer" class="tl-name tl-name--link tl-name--multi" title={mws.display_name}>
								{mws.display_name}
							</a>
						{:else}
							<span class="tl-name tl-name--multi" title={mws.display_name}>{mws.display_name}</span>
						{/if}
					</div>
				</foreignObject>

					<!-- MultiWorkshop bar -->
					{#if mws.catalog_url}
						<a href={mws.catalog_url} target="_blank" rel="noopener noreferrer" aria-label="Open {mws.display_name} in catalog">
							<rect
								x={LABEL_WIDTH + barX}
								{y}
								width={barWidth}
								height={MWS_ROW_HEIGHT}
								rx="6"
								fill={workshopStatusBg(mws.status)}
								opacity={hoveredIndex === idx ? 1 : 0.6}
								stroke={workshopStatusBg(mws.status)}
								stroke-width="2"
								stroke-dasharray="4 2"
								class="timeline-bar"
								data-bar-idx={idx}
								role="button"
								tabindex="0"
								aria-label={barAriaLabel(tRow)}
								onmouseenter={(e) => handleBarEnter(idx, e)}
								onmousemove={handleBarMove}
								onmouseleave={() => (hoveredIndex = null)}
								onfocus={() => handleBarFocus(idx)}
								onblur={() => (hoveredIndex = null)}
							/>
						</a>
					{:else}
						<rect
							x={LABEL_WIDTH + barX}
							{y}
							width={barWidth}
							height={MWS_ROW_HEIGHT}
							rx="6"
							fill={workshopStatusBg(mws.status)}
							opacity={hoveredIndex === idx ? 1 : 0.6}
							stroke={workshopStatusBg(mws.status)}
							stroke-width="2"
							stroke-dasharray="4 2"
							class="timeline-bar"
							data-bar-idx={idx}
							role="button"
							tabindex="0"
							aria-label={barAriaLabel(tRow)}
							onmouseenter={(e) => handleBarEnter(idx, e)}
							onmousemove={handleBarMove}
							onmouseleave={() => (hoveredIndex = null)}
							onfocus={() => handleBarFocus(idx)}
							onblur={() => (hoveredIndex = null)}
						/>
					{/if}

					{#if barWidth > 100}
						<text
							x={LABEL_WIDTH + barX + 8}
							y={y + MWS_ROW_HEIGHT / 2 + 4}
							font-size="10"
							fill={workshopStatusTextColor(mws.status)}
							font-weight="600"
							pointer-events="none"
							aria-hidden="true"
						>
							{mws.children.length} workshops &middot; {mws.number_seats} seats
						</text>
					{/if}
				{:else}
					{@const tItem = tRow}
				<!-- Label with flags -->
				<foreignObject x="0" y={y} width={LABEL_WIDTH} height={ROW_HEIGHT}>
					<div class="tl-label-row">
						{#if tItem.item.white_glove || tItem.item.locked || tItem.item.disable_auto_stop}
							<span class="tl-flags">
								{#if tItem.item.white_glove}
									<span class="tl-flag tl-flag--wg" title="White-glove">WG</span>
								{/if}
								{#if tItem.item.locked}
									<span class="tl-flag tl-flag--locked" title="Locked">
										<svg viewBox="0 0 16 16" width="9" height="9" fill="currentColor" aria-hidden="true">
											<path d="M8 1a3 3 0 0 0-3 3v2H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-1V4a3 3 0 0 0-3-3zm-2 3a2 2 0 1 1 4 0v2H6V4z" />
										</svg>
									</span>
								{/if}
								{#if tItem.item.disable_auto_stop}
									<span class="tl-flag tl-flag--no-autostop" title="No auto-stop">
										<svg viewBox="0 0 16 16" width="9" height="9" fill="currentColor" aria-hidden="true">
											<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 1a6 6 0 1 1 0 12A6 6 0 0 1 8 2zM6 5v6h1.5V5H6zm2.5 0v6H10V5H8.5z" />
										</svg>
									</span>
								{/if}
							</span>
						{/if}
						{#if tItem.item.workshop_id}
							{@const cs = checkStatuses[tItem.item.workshop_id]}
							{#if cs}
								<a href="/session/{cs.session_id}" target="_blank" rel="noopener noreferrer"
									class="tl-check-dot tl-check-dot--{cs.status === 'completed' ? 'green' : cs.status === 'failed' ? 'red' : 'blue'}"
									title="Last check: {checkLabel(cs.status)}"></a>
							{/if}
							{#if onRunCheck}
								<button class="tl-run-btn" title="Run check"
									onclick={() => onRunCheck(tItem.item.workshop_id, tItem.item.cluster, tItem.item.display_name)}>
									<svg viewBox="0 0 16 16" width="8" height="8" fill="currentColor" aria-hidden="true">
										<path d="M4 2l10 6-10 6V2z" />
									</svg>
								</button>
							{/if}
						{/if}
						{#if tItem.item.catalog_url}
							<a href={tItem.item.catalog_url} target="_blank" rel="noopener noreferrer" class="tl-name tl-name--link" title={tItem.item.display_name}>
								{tItem.item.display_name}
							</a>
						{:else}
							<span class="tl-name" title={tItem.item.display_name}>{tItem.item.display_name}</span>
						{/if}
					</div>
				</foreignObject>

					<!-- Bar -->
					{#if tItem.item.catalog_url}
						<a href={tItem.item.catalog_url} target="_blank" rel="noopener noreferrer" aria-label="Open {tItem.item.display_name} in catalog">
							<rect
								x={LABEL_WIDTH + barX}
								{y}
								width={barWidth}
								height={ROW_HEIGHT}
								rx="4"
								fill={workshopStatusBg(tItem.item.status)}
								opacity={hoveredIndex === idx ? 1 : 0.8}
								class="timeline-bar"
								data-bar-idx={idx}
								role="button"
								tabindex="0"
								aria-label={barAriaLabel(tRow)}
								onmouseenter={(e) => handleBarEnter(idx, e)}
								onmousemove={handleBarMove}
								onmouseleave={() => (hoveredIndex = null)}
								onfocus={() => handleBarFocus(idx)}
								onblur={() => (hoveredIndex = null)}
							/>
						</a>
					{:else}
						<rect
							x={LABEL_WIDTH + barX}
							{y}
							width={barWidth}
							height={ROW_HEIGHT}
							rx="4"
							fill={workshopStatusBg(tItem.item.status)}
							opacity={hoveredIndex === idx ? 1 : 0.8}
							class="timeline-bar"
							data-bar-idx={idx}
							role="button"
							tabindex="0"
							aria-label={barAriaLabel(tRow)}
							onmouseenter={(e) => handleBarEnter(idx, e)}
							onmousemove={handleBarMove}
							onmouseleave={() => (hoveredIndex = null)}
							onfocus={() => handleBarFocus(idx)}
							onblur={() => (hoveredIndex = null)}
						/>
					{/if}

					<!-- Bar text -->
					{#if barWidth > 80}
						<text
							x={LABEL_WIDTH + barX + 8}
							y={y + ROW_HEIGHT / 2 + 4}
							font-size="10"
							fill={workshopStatusTextColor(tItem.item.status)}
							font-weight="500"
							pointer-events="none"
							aria-hidden="true"
						>
							{tItem.item.provision_active}/{tItem.item.provision_ordered}
							{#if tItem.item.users_total > 0}
								&middot; {tItem.item.users_assigned}/{tItem.item.users_total} users
							{/if}
							{#if tItem.item.white_glove}
								&middot; WG
							{/if}
						</text>
					{:else if barWidth > 40}
						<text
							x={LABEL_WIDTH + barX + 6}
							y={y + ROW_HEIGHT / 2 + 4}
							font-size="9"
							fill={workshopStatusTextColor(tItem.item.status)}
							font-weight="500"
							pointer-events="none"
							aria-hidden="true"
						>
							{tItem.item.provision_active}/{tItem.item.provision_ordered}
						</text>
					{/if}

					<!-- Failure indicator -->
					{#if tItem.item.provision_failed > 0}
						<circle
							cx={LABEL_WIDTH + barX + barWidth - 10}
							cy={y + 10}
							r="6"
							fill="#c9190b"
							aria-hidden="true"
						/>
						<text
							x={LABEL_WIDTH + barX + barWidth - 10}
							y={y + 13}
							text-anchor="middle"
							font-size="8"
							fill="#fff"
							font-weight="700"
							pointer-events="none"
							aria-hidden="true"
						>
							{tItem.item.provision_failed}
						</text>
					{/if}
				{/if}
			{/each}
			</svg>
		</div>

		<!-- Hover tooltip -->
		{#if hoveredIndex !== null}
			{@const hovered = timelineItems[hoveredIndex]}
			<div class="timeline-tooltip" style="left: {tooltipX}px; top: {tooltipY}px;" role="tooltip">
			{#if hovered.kind === 'multi'}
				<strong class="tooltip-name">{hovered.item.display_name}</strong>
				{#if hovered.item.requester}
					<span>User: {hovered.item.requester}{#if hovered.item.ordered_by && hovered.item.ordered_by !== hovered.item.requester} (by {hovered.item.ordered_by}){/if}</span>
				{:else if hovered.item.ordered_by}
					<span>Ordered by: {hovered.item.ordered_by}</span>
				{/if}
				<span>Start: {fmtDateTime(hovered.item.start_date)}</span>
				<span>End: {fmtDateTime(hovered.item.end_date)}</span>
				<span>Event &middot; {hovered.item.children.length} workshops</span>
				<span>Cluster: {hovered.item.cluster}</span>
				<span>Status: {workshopStatusLabel(hovered.item.status)}</span>
				<span>Seats: {hovered.item.number_seats}</span>
				{#if hovered.item.provision_failed > 0}
					<span class="tooltip-failed">Failed: {hovered.item.provision_failed}</span>
				{/if}
			{:else}
				<strong class="tooltip-name">{hovered.item.display_name}</strong>
				{#if hovered.item.requester}
					<span>User: {hovered.item.requester}{#if hovered.item.ordered_by && hovered.item.ordered_by !== hovered.item.requester} (by {hovered.item.ordered_by}){/if}</span>
				{:else if hovered.item.ordered_by}
					<span>Ordered by: {hovered.item.ordered_by}</span>
				{/if}
				{#if hovered.item.catalog_item}
					<span>Catalog: {hovered.item.catalog_item}</span>
				{/if}
				<span>Start: {fmtDateTime(hovered.item.lifespan_start)}</span>
				<span>End: {fmtDateTime(hovered.item.lifespan_end)}</span>
				<span>Cluster: {hovered.item.cluster}</span>
				<span>Status: {workshopStatusLabel(hovered.item.status)}</span>
				<span>Instances: {hovered.item.provision_active}/{hovered.item.provision_ordered}</span>
				{#if hovered.item.provision_failed > 0}
					<span class="tooltip-failed">Failed: {hovered.item.provision_failed}</span>
				{/if}
				<span>Users: {hovered.item.users_assigned}/{hovered.item.users_total}</span>
			{#if hovered.item.white_glove}<span class="tooltip-wg">White-glove</span>{/if}
			{#if hovered.item.locked}<span class="tooltip-locked">Locked</span>{/if}
			{#if hovered.item.disable_auto_stop}<span class="tooltip-no-autostop">No auto-stop</span>{/if}
				{#if hovered.item.workshop_id}
					{@const cs = checkStatuses[hovered.item.workshop_id]}
					<span class="tooltip-check-row">
						Check: {cs ? checkLabel(cs.status) : '—'}
					</span>
				{/if}
			{/if}
			</div>
		{/if}
	{/if}
</div>

<style>
	.timeline-container {
		position: relative;
		width: 100%;
	}

	.timeline-scroll {
		overflow-x: auto;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: 8px;
		background: var(--pf-t--global--background--color--primary--default, #fff);
		padding: 8px;
	}

	.timeline-svg {
		display: block;
	}

	.timeline-bar {
		cursor: pointer;
		transition: opacity 0.15s;
	}

	.timeline-bar:focus {
		outline: 2px solid var(--pf-t--global--color--brand--default, #0066cc);
		outline-offset: 1px;
	}

	.tl-label-row {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 4px;
		height: 100%;
		padding-right: 8px;
		box-sizing: border-box;
		font-family: var(--pf-t--global--font--family--body, 'RedHatText', helvetica, arial, sans-serif);
	}

	.tl-flags {
		display: flex;
		gap: 2px;
		flex-shrink: 0;
	}

	.tl-flag {
		display: inline-flex;
		align-items: center;
		padding: 1px 3px;
		border-radius: 3px;
		font-size: 0.55rem;
		font-weight: 700;
		text-transform: uppercase;
		line-height: 1;
		white-space: nowrap;
	}

	.tl-flag--wg {
		background: #fef6e6;
		color: #6b4400;
		border: 1px solid #f0c75e;
	}

	.tl-flag--locked {
		background: #e7f1fa;
		color: #003d73;
		border: 1px solid #73bcf7;
	}

	.tl-flag--no-autostop {
		background: #fef3e8;
		color: #6e3101;
		border: 1px solid #f4a460;
	}

	.tl-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 11px;
		color: #4a4a4a;
		min-width: 0;
	}

	.tl-name--link {
		color: #004080;
		text-decoration: underline;
		font-weight: 500;
	}

	.tl-name--link:hover {
		color: #0066cc;
	}

	.tl-name--multi {
		color: #003d73;
		font-weight: 600;
	}

	.timeline-empty {
		text-align: center;
		padding: 48px;
		opacity: 0.6;
	}

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

	.tl-check-dot {
		display: inline-block;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.tl-check-dot--green { background: #6ec071; }
	.tl-check-dot--red { background: #e87a72; }
	.tl-check-dot--blue { background: #73bcf7; }

	.tl-run-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 16px;
		height: 16px;
		border: none;
		background: none;
		cursor: pointer;
		border-radius: 3px;
		color: var(--pf-t--global--icon--color--regular, #6a6e73);
		flex-shrink: 0;
		padding: 0;
		transition: color 0.15s;
	}

	.tl-run-btn:hover {
		color: var(--pf-t--global--color--brand--default, #0066cc);
	}
</style>
