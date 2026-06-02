<script lang="ts">
	import type { WorkshopSummary } from '$lib/types';

	let { summary }: { summary: WorkshopSummary } = $props();
</script>

<section class="summary-strip" aria-label="Workshop summary">
	<div class="summary-item">
		<span class="summary-item__value">{summary.total}</span>
		<span class="summary-item__label">Total</span>
	</div>
	<div class="summary-item summary-item--blue">
		<span class="summary-item__value">{summary.provisioning}</span>
		<span class="summary-item__label">Provisioning</span>
	</div>
	<div class="summary-item summary-item--green">
		<span class="summary-item__value">{summary.running}</span>
		<span class="summary-item__label">Running</span>
	</div>
	<div class="summary-item summary-item--muted">
		<span class="summary-item__value">{summary.stopped}</span>
		<span class="summary-item__label">Stopped</span>
	</div>
	<div class="summary-item summary-item--orange">
		<span class="summary-item__value">{summary.degraded + summary.failed}</span>
		<span class="summary-item__label">Attention</span>
	</div>
	<div class="summary-item summary-item--gold">
		<span class="summary-item__value">{summary.scheduled}</span>
		<span class="summary-item__label">Scheduled</span>
	</div>
</section>

<style>
	.summary-strip {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: var(--pf-t--global--spacer--sm, 8px);
	}

	.summary-item {
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 4px 10px;
		border-radius: 6px;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		background: var(--pf-t--global--background--color--primary--default, #fff);
	}

	.summary-item__value {
		font-size: 1rem;
		font-weight: 700;
		line-height: 1;
	}

	.summary-item__label {
		font-size: 0.65rem;
		opacity: 0.6;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		white-space: nowrap;
	}

	.summary-item--blue {
		border-color: var(--sc-blue-border);
		background: var(--sc-blue-bg);
	}
	.summary-item--blue .summary-item__value { color: var(--sc-blue-text); }

	.summary-item--green {
		border-color: var(--sc-green-border);
		background: var(--sc-green-bg);
	}
	.summary-item--green .summary-item__value { color: var(--sc-green-text); }

	.summary-item--orange {
		border-color: var(--sc-red-border);
		background: var(--sc-red-bg);
	}
	.summary-item--orange .summary-item__value { color: var(--sc-red-text); }

	.summary-item--gold {
		border-color: var(--sc-gold-border);
		background: var(--sc-gold-bg);
	}
	.summary-item--gold .summary-item__value { color: var(--sc-gold-text); }

	.summary-item--muted {
		border-color: var(--sc-muted-border);
		background: var(--sc-muted-bg);
	}
	.summary-item--muted .summary-item__value { color: var(--sc-muted-text); }
</style>
