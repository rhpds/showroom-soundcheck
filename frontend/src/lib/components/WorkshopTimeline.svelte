<script lang="ts">
	import { onMount } from 'svelte';
	import type { MultiWorkshopDashboardItem, WorkshopDashboardItem, WorkshopStatus, WorkshopCheckStatusMap } from '$lib/types';
	import { workshopStatusBg, workshopStatusTextColor, workshopStatusLabel, workshopStatusBorder } from '$lib/utils';
	import { checkStatusLabel } from '$lib/checkStatuses.svelte';
	import TimelineTooltip from './TimelineTooltip.svelte';

	let {
		items,
		multiWorkshops = [],
		filterFrom,
		filterTo,
		timeWindow,
		checkStatuses = {},
		onRunCheck,
		expandedMultiWorkshops = new Set<string>(),
		onToggleMultiWorkshop
	}: {
		items: WorkshopDashboardItem[];
		multiWorkshops?: MultiWorkshopDashboardItem[];
		filterFrom?: string;
		filterTo?: string;
		timeWindow?: 'all' | 'today' | '24h' | 'week';
		checkStatuses?: WorkshopCheckStatusMap;
		onRunCheck?: (workshopId: string, cluster: string, displayName: string) => void;
		expandedMultiWorkshops?: Set<string>;
		onToggleMultiWorkshop?: (name: string) => void;
	} = $props();

	let containerWidth = $state(800);
	let container: HTMLDivElement;

	onMount(() => {
		let rafId: number;
		const observer = new ResizeObserver((entries) => {
			cancelAnimationFrame(rafId);
			rafId = requestAnimationFrame(() => {
				for (const entry of entries) {
					containerWidth = entry.contentRect.width;
				}
			});
		});
		observer.observe(container);
		return () => {
			cancelAnimationFrame(rafId);
			observer.disconnect();
		};
	});

	const ROW_HEIGHT = 52;
	const ROW_GAP = 4;
	const LABEL_WIDTH = 240;
	const PADDING_TOP = 40;
	const HEADER_HEIGHT = 30;

	const CHILD_ROW_HEIGHT = 48;
	const MWS_ROW_HEIGHT = 52;
	const SCROLL_CHROME = 18; // .timeline-scroll padding (8*2) + border (1*2)

	type TimelineRow =
		| { kind: 'workshop'; item: WorkshopDashboardItem; startMs: number; endMs: number }
		| { kind: 'multi'; item: MultiWorkshopDashboardItem; startMs: number; endMs: number }
		| { kind: 'child'; item: WorkshopDashboardItem; parentName: string; startMs: number; endMs: number };

	let timelineItems = $derived.by(() => {
		const now = Date.now();
		const rows: TimelineRow[] = [];

		const multiRows: { row: TimelineRow; sortMs: number }[] = [];
		const standaloneRows: { row: TimelineRow; sortMs: number }[] = [];

		for (const mws of multiWorkshops) {
			const startMs = mws.start_date ? new Date(mws.start_date).getTime() : now;
			let endMs = mws.end_date ? new Date(mws.end_date).getTime() : now + 4 * 3600000;
			if (endMs <= startMs) endMs = startMs + 3600000;
			if (!isNaN(startMs) && !isNaN(endMs)) {
				multiRows.push({
					row: { kind: 'multi', item: mws, startMs, endMs },
					sortMs: startMs
				});
			}
		}

		for (const item of items) {
			const startMs = item.lifespan_start ? new Date(item.lifespan_start).getTime() : now;
			let endMs = item.lifespan_end ? new Date(item.lifespan_end).getTime() : now + 4 * 3600000;
			if (endMs <= startMs) endMs = startMs + 3600000;
			if (!isNaN(startMs) && !isNaN(endMs)) {
				standaloneRows.push({
					row: { kind: 'workshop', item, startMs, endMs },
					sortMs: startMs
				});
			}
		}

		const combined = [...multiRows, ...standaloneRows];
		combined.sort((a, b) => a.sortMs - b.sortMs);

		for (const { row } of combined) {
			rows.push(row);
			if (row.kind === 'multi' && expandedMultiWorkshops.has(row.item.name)) {
				for (const child of row.item.children) {
					const childStart = child.lifespan_start ? new Date(child.lifespan_start).getTime() : row.startMs;
					let childEnd = child.lifespan_end ? new Date(child.lifespan_end).getTime() : row.endMs;
					if (childEnd <= childStart) childEnd = childStart + 3600000;
					rows.push({ kind: 'child', item: child, parentName: row.item.name, startMs: childStart, endMs: childEnd });
				}
			}
		}

		return rows;
	});

	function rowHeight(row: TimelineRow): number {
		if (row.kind === 'multi') return MWS_ROW_HEIGHT;
		if (row.kind === 'child') return CHILD_ROW_HEIGHT;
		return ROW_HEIGHT;
	}

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

	let chartWidth = $derived(Math.max(containerWidth - LABEL_WIDTH - 20 - SCROLL_CHROME, 200));

	let rowYPositions = $derived.by(() => {
		const positions: number[] = [];
		let y = PADDING_TOP + HEADER_HEIGHT;
		for (const row of timelineItems) {
			positions.push(y);
			y += rowHeight(row) + ROW_GAP;
		}
		return positions;
	});

	let svgHeight = $derived.by(() => {
		if (timelineItems.length === 0) return PADDING_TOP + HEADER_HEIGHT + 60;
		const lastIdx = timelineItems.length - 1;
		return rowYPositions[lastIdx] + rowHeight(timelineItems[lastIdx]) + 20;
	});

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

	function statusShortLabel(status: WorkshopStatus): string {
		switch (status) {
			case 'running': return 'RUN';
			case 'provisioning': return 'PROV';
			case 'scheduled': return 'SCHED';
			case 'stopped': return 'STOP';
			case 'degraded': return 'DEG';
			case 'failed': return 'FAIL';
			case 'completed': return 'DONE';
			default: return '?';
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
				{@const y = rowYPositions[idx]}
				{@const h = rowHeight(tRow)}
				{@const rawBarX = msToX(tRow.startMs)}
				{@const rawBarEnd = msToX(tRow.endMs)}
				{@const barX = Math.max(rawBarX, 0)}
				{@const barWidth = Math.max(Math.min(rawBarEnd, chartWidth) - barX, 4)}

				{#if tRow.kind === 'multi'}
					{@const mws = tRow.item}
					{@const isExpanded = expandedMultiWorkshops.has(mws.name)}
				<!-- MultiWorkshop two-line label -->
				<foreignObject x="0" {y} width={LABEL_WIDTH} height={h}>
					<div class="tl-label-col">
						<div class="tl-label-line1">
							{#if onToggleMultiWorkshop}
								<button
									class="tl-expand-btn"
									class:tl-expand-btn--open={isExpanded}
									onclick={() => onToggleMultiWorkshop(mws.name)}
									aria-label={isExpanded ? 'Collapse' : 'Expand'}
									title="{mws.children.length} workshops"
								>
									<svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor" aria-hidden="true">
										<path d="M6 3l5 5-5 5V3z" />
									</svg>
								</button>
							{/if}
							{#if mws.catalog_url}
								<a href={mws.catalog_url} target="_blank" rel="noopener noreferrer" class="tl-name tl-name--link tl-name--multi" title={mws.display_name}>
									{mws.display_name}
								</a>
							{:else}
								<span class="tl-name tl-name--multi" title={mws.display_name}>{mws.display_name}</span>
							{/if}
						</div>
						<div class="tl-label-line2">
							<span class="tl-meta">{mws.children.length} workshops &middot; {mws.number_seats} seats</span>
							<span class="tl-cluster">{mws.cluster}</span>
						</div>
					</div>
				</foreignObject>

					<!-- MultiWorkshop bar -->
					{#if mws.catalog_url}
						<a href={mws.catalog_url} target="_blank" rel="noopener noreferrer" aria-label="Open {mws.display_name} in catalog">
							<rect
								x={LABEL_WIDTH + barX}
								{y}
								width={barWidth}
								height={h}
								rx="6"
								fill={workshopStatusBg(mws.status)}
								opacity={hoveredIndex === idx ? 1 : 0.6}
								stroke={workshopStatusBorder(mws.status)}
								stroke-width="2"
								stroke-dasharray="4 2"
								class="timeline-bar"
								data-bar-idx={idx}
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
							height={h}
							rx="6"
							fill={workshopStatusBg(mws.status)}
							opacity={hoveredIndex === idx ? 1 : 0.6}
							stroke={workshopStatusBorder(mws.status)}
							stroke-width="2"
							stroke-dasharray="4 2"
							class="timeline-bar"
							data-bar-idx={idx}
							role="img"
							tabindex="0"
							aria-label={barAriaLabel(tRow)}
							onmouseenter={(e) => handleBarEnter(idx, e)}
							onmousemove={handleBarMove}
							onmouseleave={() => (hoveredIndex = null)}
							onfocus={() => handleBarFocus(idx)}
							onblur={() => (hoveredIndex = null)}
						/>
					{/if}

					{#if barWidth > 160}
						<text
							x={LABEL_WIDTH + barX + 8}
							y={y + h / 2 + 4}
							font-size="10"
							fill={workshopStatusTextColor(mws.status)}
							font-weight="600"
							pointer-events="none"
							aria-hidden="true"
						>
							{statusShortLabel(mws.status)} &middot; {mws.children.length} workshops &middot; {mws.number_seats} seats
						</text>
					{:else if barWidth > 80}
						<text
							x={LABEL_WIDTH + barX + 8}
							y={y + h / 2 + 4}
							font-size="10"
							fill={workshopStatusTextColor(mws.status)}
							font-weight="600"
							pointer-events="none"
							aria-hidden="true"
						>
							{mws.children.length} workshops &middot; {mws.number_seats} seats
						</text>
					{/if}

				{:else if tRow.kind === 'child'}
					{@const child = tRow.item}
				<!-- Child workshop two-line label (indented) -->
				<foreignObject x="0" {y} width={LABEL_WIDTH} height={h}>
					<div class="tl-label-col tl-label-col--child">
						<div class="tl-label-line1">
							<span class="tl-child-indent"></span>
							{#if child.catalog_url}
								<a href={child.catalog_url} target="_blank" rel="noopener noreferrer" class="tl-name tl-name--link" title={child.display_name}>
									{child.display_name}
								</a>
							{:else}
								<span class="tl-name" title={child.display_name}>{child.display_name}</span>
							{/if}
						</div>
						<div class="tl-label-line2 tl-label-line2--child">
							<span class="tl-child-indent"></span>
							{#if child.white_glove}
								<span class="tl-flag tl-flag--wg" title="White-glove">WG</span>
							{/if}
							{#if child.locked}
								<span class="tl-flag tl-flag--locked" title="Locked">
									<svg viewBox="0 0 16 16" width="9" height="9" fill="currentColor" aria-hidden="true">
										<path d="M8 1a3 3 0 0 0-3 3v2H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-1V4a3 3 0 0 0-3-3zm-2 3a2 2 0 1 1 4 0v2H6V4z" />
									</svg>
								</span>
							{/if}
							{#if child.disable_auto_stop}
								<span class="tl-flag tl-flag--no-autostop" title="No auto-stop">
									<svg viewBox="0 0 16 16" width="9" height="9" fill="currentColor" aria-hidden="true">
										<path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 1a6 6 0 1 1 0 12A6 6 0 0 1 8 2zM6 5v6h1.5V5H6zm2.5 0v6H10V5H8.5z" />
									</svg>
								</span>
							{/if}
							{#if child.workshop_id}
							{@const cs = checkStatuses[child.workshop_id]}
							{#if cs}
								<a href="/session/{cs.session_id}" target="_blank" rel="noopener noreferrer"
									class="tl-check-dot tl-check-dot--{cs.status === 'completed' ? 'green' : cs.status === 'failed' ? 'red' : 'blue'}"
									title="Last check: {checkStatusLabel(cs.status)}"
									aria-label="Last check: {checkStatusLabel(cs.status)}"></a>
							{/if}
							{#if onRunCheck && child.status !== 'scheduled' && child.status !== 'completed'}
								<button class="tl-run-btn" title="Run check"
									onclick={() => onRunCheck(child.workshop_id, child.cluster, child.display_name)}>
									<svg viewBox="0 0 16 16" width="8" height="8" fill="currentColor" aria-hidden="true">
										<path d="M4 2l10 6-10 6V2z" />
									</svg>
								</button>
							{/if}
						{/if}
						</div>
					</div>
				</foreignObject>

					<!-- Child bar -->
					{#if child.catalog_url}
						<a href={child.catalog_url} target="_blank" rel="noopener noreferrer" aria-label="Open {child.display_name} in catalog">
							<rect
								x={LABEL_WIDTH + barX}
								{y}
								width={barWidth}
								height={h}
								rx="4"
								fill={workshopStatusBg(child.status)}
								opacity={hoveredIndex === idx ? 1 : 0.8}
								class="timeline-bar"
								data-bar-idx={idx}
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
							height={h}
							rx="4"
							fill={workshopStatusBg(child.status)}
							opacity={hoveredIndex === idx ? 1 : 0.8}
							class="timeline-bar"
							data-bar-idx={idx}
							role="img"
							tabindex="0"
							aria-label={barAriaLabel(tRow)}
							onmouseenter={(e) => handleBarEnter(idx, e)}
							onmousemove={handleBarMove}
							onmouseleave={() => (hoveredIndex = null)}
							onfocus={() => handleBarFocus(idx)}
							onblur={() => (hoveredIndex = null)}
						/>
					{/if}

					{#if barWidth > 160}
						<text
							x={LABEL_WIDTH + barX + 8}
							y={y + h / 2 + 4}
							font-size="10"
							fill={workshopStatusTextColor(child.status)}
							font-weight="500"
							pointer-events="none"
							aria-hidden="true"
						>
							{statusShortLabel(child.status)} &middot; {child.provision_active}/{child.provision_ordered}
							{#if child.users_total > 0}
								&middot; {child.users_assigned}/{child.users_total} users
							{/if}
						</text>
					{:else if barWidth > 80}
						<text
							x={LABEL_WIDTH + barX + 8}
							y={y + h / 2 + 4}
							font-size="10"
							fill={workshopStatusTextColor(child.status)}
							font-weight="500"
							pointer-events="none"
							aria-hidden="true"
						>
							{child.provision_active}/{child.provision_ordered}
							{#if child.users_total > 0}
								&middot; {child.users_assigned}/{child.users_total}
							{/if}
						</text>
					{:else if barWidth > 40}
						<text
							x={LABEL_WIDTH + barX + 6}
							y={y + h / 2 + 4}
							font-size="9"
							fill={workshopStatusTextColor(child.status)}
							font-weight="500"
							pointer-events="none"
							aria-hidden="true"
						>
							{child.provision_active}/{child.provision_ordered}
						</text>
					{/if}

					{#if child.provision_failed > 0}
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
							{child.provision_failed}
						</text>
					{/if}

				{:else}
					{@const tItem = tRow}
				<!-- Standalone workshop two-line label -->
				<foreignObject x="0" {y} width={LABEL_WIDTH} height={h}>
					<div class="tl-label-col">
						<div class="tl-label-line1">
							{#if tItem.item.catalog_url}
								<a href={tItem.item.catalog_url} target="_blank" rel="noopener noreferrer" class="tl-name tl-name--link" title={tItem.item.display_name}>
									{tItem.item.display_name}
								</a>
							{:else}
								<span class="tl-name" title={tItem.item.display_name}>{tItem.item.display_name}</span>
							{/if}
						</div>
						<div class="tl-label-line2">
							{#if tItem.item.white_glove}
								<span class="tl-flag tl-flag--wg" title="White-glove">WG</span>
							{/if}
							{#if tItem.item.demo_team_provisioned}
								<span class="tl-flag tl-flag--dt" title="Demo team">DT</span>
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
						{#if tItem.item.workshop_id}
							{@const cs = checkStatuses[tItem.item.workshop_id]}
							{#if cs}
								<a href="/session/{cs.session_id}" target="_blank" rel="noopener noreferrer"
									class="tl-check-dot tl-check-dot--{cs.status === 'completed' ? 'green' : cs.status === 'failed' ? 'red' : 'blue'}"
									title="Last check: {checkStatusLabel(cs.status)}"
									aria-label="Last check: {checkStatusLabel(cs.status)}"></a>
							{/if}
							{#if onRunCheck && tItem.item.status !== 'scheduled' && tItem.item.status !== 'completed'}
								<button class="tl-run-btn" title="Run check"
									onclick={() => onRunCheck(tItem.item.workshop_id, tItem.item.cluster, tItem.item.display_name)}>
									<svg viewBox="0 0 16 16" width="8" height="8" fill="currentColor" aria-hidden="true">
										<path d="M4 2l10 6-10 6V2z" />
									</svg>
								</button>
							{/if}
						{/if}
							{#if tItem.item.requester}
								<span class="tl-requester">{tItem.item.requester}</span>
							{/if}
						</div>
					</div>
				</foreignObject>

					<!-- Bar -->
					{#if tItem.item.catalog_url}
						<a href={tItem.item.catalog_url} target="_blank" rel="noopener noreferrer" aria-label="Open {tItem.item.display_name} in catalog">
							<rect
								x={LABEL_WIDTH + barX}
								{y}
								width={barWidth}
								height={h}
								rx="4"
								fill={workshopStatusBg(tItem.item.status)}
								opacity={hoveredIndex === idx ? 1 : 0.8}
								class="timeline-bar"
								data-bar-idx={idx}
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
							height={h}
							rx="4"
							fill={workshopStatusBg(tItem.item.status)}
							opacity={hoveredIndex === idx ? 1 : 0.8}
							class="timeline-bar"
							data-bar-idx={idx}
							role="img"
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
					{#if barWidth > 160}
						<text
							x={LABEL_WIDTH + barX + 8}
							y={y + h / 2 + 4}
							font-size="10"
							fill={workshopStatusTextColor(tItem.item.status)}
							font-weight="500"
							pointer-events="none"
							aria-hidden="true"
						>
							{statusShortLabel(tItem.item.status)} &middot; {tItem.item.provision_active}/{tItem.item.provision_ordered}
							{#if tItem.item.users_total > 0}
								&middot; {tItem.item.users_assigned}/{tItem.item.users_total} users
							{/if}
						</text>
					{:else if barWidth > 80}
						<text
							x={LABEL_WIDTH + barX + 8}
							y={y + h / 2 + 4}
							font-size="10"
							fill={workshopStatusTextColor(tItem.item.status)}
							font-weight="500"
							pointer-events="none"
							aria-hidden="true"
						>
							{tItem.item.provision_active}/{tItem.item.provision_ordered}
							{#if tItem.item.users_total > 0}
								&middot; {tItem.item.users_assigned}/{tItem.item.users_total}
							{/if}
						</text>
					{:else if barWidth > 40}
						<text
							x={LABEL_WIDTH + barX + 6}
							y={y + h / 2 + 4}
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

		{#if hoveredIndex !== null}
			<TimelineTooltip
				row={timelineItems[hoveredIndex]}
				x={tooltipX}
				y={tooltipY}
				{checkStatuses}
			/>
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

	/* Two-line label layout */
	.tl-label-col {
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: 2px;
		height: 100%;
		padding-right: 8px;
		padding-left: 4px;
		box-sizing: border-box;
		font-family: var(--pf-t--global--font--family--body, 'RedHatText', helvetica, arial, sans-serif);
	}

	.tl-label-col--child {
		padding-left: 0;
	}

	.tl-label-line1 {
		display: flex;
		align-items: center;
		gap: 4px;
		min-width: 0;
	}

	.tl-label-line2 {
		display: flex;
		align-items: center;
		gap: 3px;
		min-width: 0;
		flex-wrap: wrap;
	}

	.tl-label-line2--child {
		padding-left: 0;
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
		background: var(--sc-gold-bg);
		color: var(--sc-gold-text);
		border: 1px solid var(--sc-gold-border);
	}

	.tl-flag--dt {
		background: var(--sc-purple-bg);
		color: var(--sc-purple-text);
		border: 1px solid var(--sc-purple-border);
	}

	.tl-flag--locked {
		background: var(--sc-blue-bg);
		color: var(--sc-blue-text);
		border: 1px solid var(--sc-blue-border);
	}

	.tl-flag--no-autostop {
		background: var(--sc-orange-bg);
		color: var(--sc-orange-text);
		border: 1px solid var(--sc-orange-border);
	}

	.tl-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 11px;
		color: var(--pf-t--global--text--color--regular, #151515);
		min-width: 0;
	}

	.tl-name--link {
		color: var(--pf-t--global--color--link--default, #0066cc);
		text-decoration: underline;
		font-weight: 500;
	}

	.tl-name--link:hover {
		color: var(--pf-t--global--color--link--hover, #004080);
	}

	.tl-name--multi {
		color: var(--pf-t--global--color--link--default, #0066cc);
		font-weight: 600;
	}

	.tl-meta {
		font-size: 0.6rem;
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		white-space: nowrap;
	}

	.tl-cluster {
		font-size: 0.55rem;
		padding: 0 3px;
		border-radius: 3px;
		background: var(--sc-blue-bg);
		color: var(--sc-blue-text);
		border: 1px solid var(--sc-blue-border);
		white-space: nowrap;
	}

	.tl-requester {
		font-size: 0.6rem;
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}

	/* Expand/collapse button for multi-workshops */
	.tl-expand-btn {
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
		transition: transform 0.15s, color 0.15s;
	}

	.tl-expand-btn:hover {
		color: var(--pf-t--global--color--brand--default, #0066cc);
	}

	.tl-expand-btn--open {
		transform: rotate(90deg);
	}

	/* Child row indent */
	.tl-child-indent {
		display: inline-block;
		width: 14px;
		flex-shrink: 0;
		border-left: 2px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-bottom: 2px solid var(--pf-t--global--border--color--default, #d2d2d2);
		height: 8px;
		margin-left: 6px;
		margin-bottom: -2px;
	}

	.timeline-empty {
		text-align: center;
		padding: 48px;
		opacity: 0.6;
	}

	.tl-check-dot {
		display: inline-block;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.tl-check-dot--green { background: var(--sc-green-border); }
	.tl-check-dot--red { background: var(--sc-red-border); }
	.tl-check-dot--blue { background: var(--sc-blue-border); }

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
