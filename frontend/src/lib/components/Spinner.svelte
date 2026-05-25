<script lang="ts">
	let {
		label = 'Loading',
		size,
		text
	}: {
		label?: string;
		size?: 'sm' | 'md' | 'lg' | 'xl';
		text?: string;
	} = $props();
</script>

<span
	class="heartbeat-spinner {size ? `heartbeat-spinner--${size}` : ''}"
	class:heartbeat-spinner--block={text}
	role="progressbar"
	aria-label={label}
>
	<span class="heartbeat-spinner__icon">
		<svg viewBox="1 4 30 24" fill="none" aria-hidden="true">
			<polyline
				points="4,16 9,16 12,16 14,7 16,24 18,11 20,16 23,16 28,16"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		</svg>
	</span>
	{#if text}
		<span class="heartbeat-spinner__text">{text}</span>
	{/if}
</span>

<style>
	.heartbeat-spinner {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		color: #a0aab8;
	}

	.heartbeat-spinner--block {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 16px;
		padding: 40px 24px;
	}

	.heartbeat-spinner__icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}

	.heartbeat-spinner--block .heartbeat-spinner__icon {
		background: var(--pf-t--global--background--color--secondary--default, #f4f5f7);
		border-radius: 20px;
		padding: 18px 28px;
	}

	.heartbeat-spinner svg {
		width: 48px;
		display: block;
		animation: heartbeat-pulse 2.4s ease-in-out infinite;
	}

	.heartbeat-spinner--sm svg {
		width: 20px;
	}

	.heartbeat-spinner--lg svg {
		width: 64px;
	}

	.heartbeat-spinner--xl svg {
		width: 80px;
	}

	.heartbeat-spinner__text {
		font-size: var(--pf-t--global--font--size--body--default, 0.9375rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		letter-spacing: 0.02em;
	}

	@keyframes heartbeat-pulse {
		0%,
		100% {
			transform: scale(1);
			opacity: 0.45;
		}
		15% {
			transform: scale(1.12);
			opacity: 1;
		}
		30% {
			transform: scale(1);
			opacity: 0.45;
		}
		45% {
			transform: scale(1.08);
			opacity: 0.8;
		}
		60% {
			transform: scale(1);
			opacity: 0.45;
		}
	}
</style>
