<script lang="ts">
	import { statusColor } from '$lib/types';
	import type { Status } from '$lib/types';

	let { status, size = 'md' }: { status: Status; size?: 'sm' | 'md' } = $props();

	const colorMap: Record<string, string> = {
		green: 'pf-m-green',
		red: 'pf-m-red',
		blue: 'pf-m-blue',
		gold: 'pf-m-gold',
		orange: 'pf-m-orange',
		grey: ''
	};

	const labelMap: Record<string, string> = {
		healthy: 'Healthy',
		completed: 'All Passed',
		degraded: 'Degraded',
		error: 'Error',
		unhealthy: 'Unhealthy',
		failed: 'Issues Found',
		running: 'Running',
		pending: 'Pending',
		provisioning: 'Provisioning'
	};

	let color = $derived(statusColor(status));
	let pfClass = $derived(colorMap[color] || '');
	let label = $derived(labelMap[status] || status);
</script>

<span class="status-badge status-badge--{color} {pfClass}" class:status-badge--sm={size === 'sm'}>
	<span class="status-badge__icon">
		{#if status === 'healthy' || status === 'completed'}
			<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
				><path
					d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm3.36 4.65a.5.5 0 0 0-.72-.02L7.2 8.94 5.35 7.17a.5.5 0 1 0-.7.71l2.2 2.12a.5.5 0 0 0 .7-.01l3.8-3.63a.5.5 0 0 0 .01-.71Z"
				/></svg
			>
		{:else if status === 'error' || status === 'unhealthy' || status === 'failed'}
			<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
				><path
					d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm2.35 4.65a.5.5 0 0 0-.7 0L8 7.29 6.35 5.65a.5.5 0 1 0-.7.7L7.29 8 5.65 9.65a.5.5 0 1 0 .7.7L8 8.71l1.65 1.64a.5.5 0 0 0 .7-.7L8.71 8l1.64-1.65a.5.5 0 0 0 0-.7Z"
				/></svg
			>
		{:else if status === 'degraded'}
			<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
				><path
					d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
				/></svg
			>
		{:else if status === 'running'}
			<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" class="status-badge__spin"
				><path d="M8 1.5a6.5 6.5 0 1 0 6.5 6.5h-1.3A5.2 5.2 0 1 1 8 2.8V1.5Z" /></svg
			>
		{:else if status === 'pending'}
			<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
				><path
					d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm.5 3a.5.5 0 0 0-1 0v4.25l2.9 1.74a.5.5 0 0 0 .51-.86L8.5 7.68V4Z"
				/></svg
			>
		{:else if status === 'provisioning'}
			<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
				><path
					d="M6.5 1a.5.5 0 0 1 .49.4L8.2 7h2.3a.5.5 0 0 1 .35.85l-4.5 4.5a.5.5 0 0 1-.84-.25L4.3 8H2.5a.5.5 0 0 1-.38-.82l4-4.5A.5.5 0 0 1 6.5 1Z"
				/></svg
			>
		{/if}
	</span>
	<span class="status-badge__text">{label}</span>
</span>

<style>
	.status-badge {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 4px 10px;
		border-radius: 20px;
		font-size: 0.8125rem;
		font-weight: 500;
		line-height: 1;
		white-space: nowrap;
		border: 1px solid;
	}

	.status-badge--sm {
		padding: 2px 8px;
		font-size: 0.75rem;
		gap: 4px;
	}

	.status-badge__icon {
		display: inline-flex;
		align-items: center;
		width: 14px;
		height: 14px;
		flex-shrink: 0;
	}

	.status-badge--sm .status-badge__icon {
		width: 12px;
		height: 12px;
	}

	.status-badge__icon :global(svg) {
		width: 100%;
		height: 100%;
	}

	.status-badge__text {
		line-height: 1.2;
	}

	@keyframes spin {
		from {
			transform: rotate(0deg);
		}
		to {
			transform: rotate(360deg);
		}
	}

	.status-badge__icon :global(.status-badge__spin) {
		animation: spin 1s linear infinite;
	}

	.status-badge--green {
		color: #1e4620;
		background: #e7f5e8;
		border-color: #6ec071;
	}

	.status-badge--red {
		color: #7d1007;
		background: #fce8e6;
		border-color: #e87a72;
	}

	.status-badge--gold {
		color: #6b4400;
		background: #fef6e6;
		border-color: #f0c75e;
	}

	.status-badge--blue {
		color: #003d73;
		background: #e7f1fa;
		border-color: #73bcf7;
	}

	.status-badge--orange {
		color: #6e3101;
		background: #fef3e8;
		border-color: #f4a460;
	}

	.status-badge--grey,
	.status-badge-- {
		color: #3c3f42;
		background: #f0f0f0;
		border-color: #d2d2d2;
	}
</style>
