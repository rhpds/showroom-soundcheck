<script lang="ts">
	import { focusTrap } from '$lib/actions/focusTrap';
	import { portal } from '$lib/actions/portal';

	let {
		title,
		size = 'md',
		onClose,
		children
	}: {
		title: string;
		size?: 'sm' | 'md' | 'lg';
		onClose: () => void;
		children: import('svelte').Snippet;
	} = $props();

	const titleId = `modal-title-${Math.random().toString(36).slice(2, 9)}`;

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.stopPropagation();
			onClose();
		}
	}
</script>

<div
	class="pf-v6-c-backdrop"
	onclick={onClose}
	onkeydown={handleKeydown}
	role="presentation"
	use:portal
>
	<div
		class="pf-v6-c-modal-box pf-m-{size}"
		role="dialog"
		aria-modal="true"
		aria-labelledby={titleId}
		aria-describedby="{titleId}-body"
		tabindex="-1"
		onclick={(e) => e.stopPropagation()}
		onkeydown={handleKeydown}
		use:focusTrap
	>
		<div class="pf-v6-c-modal-box__close">
			<button class="pf-v6-c-button pf-m-plain" onclick={onClose} aria-label="Close">
				<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor"
					><path
						d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708Z"
					/></svg
				>
			</button>
		</div>
		<div class="pf-v6-c-modal-box__header">
			<h1 class="pf-v6-c-modal-box__title" id={titleId}>{title}</h1>
		</div>
		<div class="pf-v6-c-modal-box__body" id="{titleId}-body" tabindex="0">
			{@render children()}
		</div>
	</div>
</div>

<style>
	.pf-v6-c-backdrop {
		display: flex;
		align-items: center;
		justify-content: center;
	}
</style>
