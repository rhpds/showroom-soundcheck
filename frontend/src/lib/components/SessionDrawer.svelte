<script lang="ts">
	import { portal } from '$lib/actions/portal';
	import { focusTrap } from '$lib/actions/focusTrap';
	import SessionContent from './SessionContent.svelte';

	let {
		sessionId,
		onClose,
		onRerun
	}: {
		sessionId: string;
		onClose: () => void;
		onRerun?: (sourceType: string, sourceValue: string) => void;
	} = $props();

	let overrideId = $state<string | null>(null);
	let activeSessionId = $derived(overrideId ?? sessionId);

	$effect(() => {
		void sessionId;
		overrideId = null;
	});

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
	}

	function handleNavigate(id: string) {
		overrideId = id;
	}
</script>

<div
	class="drawer-backdrop"
	onclick={onClose}
	onkeydown={handleKeydown}
	role="presentation"
	use:portal
>
	<aside
		class="drawer"
		role="dialog"
		aria-modal="true"
		aria-label="Session details"
		tabindex="-1"
		onclick={(e) => e.stopPropagation()}
		onkeydown={handleKeydown}
		use:focusTrap
	>
		<div class="drawer__toolbar">
			<a
				class="pf-v6-c-button pf-m-link pf-m-sm"
				href="/session/{activeSessionId}"
				target="_blank"
				rel="noopener noreferrer">Open full page ↗</a
			>
			<button class="pf-v6-c-button pf-m-plain" onclick={onClose} aria-label="Close">✕</button>
		</div>
		<div class="drawer__body">
			<SessionContent sessionId={activeSessionId} onNavigate={handleNavigate} {onRerun} />
		</div>
	</aside>
</div>

<style>
	.drawer-backdrop {
		position: fixed;
		inset: 0;
		z-index: 350;
		background: rgba(0, 0, 0, 0.5);
		display: flex;
		justify-content: flex-end;
	}

	.drawer {
		width: min(720px, 95vw);
		height: 100%;
		background: var(--pf-t--global--background--color--secondary--default, #f0f0f0);
		box-shadow: -4px 0 16px rgba(0, 0, 0, 0.15);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		animation: slide-in 0.15s ease-out;
		z-index: 351;
	}

	@keyframes slide-in {
		from {
			transform: translateX(100%);
		}
		to {
			transform: translateX(0);
		}
	}

	.drawer__toolbar {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 4px;
		padding: 8px 16px;
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		background: var(--pf-t--global--background--color--primary--default, #fff);
		flex-shrink: 0;
	}

	.drawer__body {
		flex: 1;
		overflow-y: auto;
		padding: 0 var(--pf-t--global--spacer--md, 16px) var(--pf-t--global--spacer--md, 16px);
	}
</style>
