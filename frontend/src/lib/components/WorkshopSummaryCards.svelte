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
		border-color: #73bcf7;
		background: #e7f1fa;
	}
	.summary-item--blue .summary-item__value { color: #003d73; }

	.summary-item--green {
		border-color: #6ec071;
		background: #e7f5e8;
	}
	.summary-item--green .summary-item__value { color: #1e4620; }

	.summary-item--orange {
		border-color: #e87a72;
		background: #fce8e6;
	}
	.summary-item--orange .summary-item__value { color: #7d1007; }

	.summary-item--gold {
		border-color: #f0c75e;
		background: #fef6e6;
	}
	.summary-item--gold .summary-item__value { color: #6b4400; }

	.summary-item--muted {
		border-color: #b8bbbe;
		background: #f0f0f0;
	}
	.summary-item--muted .summary-item__value { color: #3e4045; }
</style>
