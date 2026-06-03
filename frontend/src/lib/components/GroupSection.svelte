<script lang="ts">
	let {
		header,
		children
	}: {
		header?: import('svelte').Snippet;
		children: import('svelte').Snippet;
	} = $props();
</script>

<div class="group-section">
	{#if header}
		<div class="group-section__header">
			{@render header()}
		</div>
	{/if}
	<div class="group-section__body">
		{@render children()}
	</div>
</div>

<style>
	.group-section {
		background: var(--pf-t--global--background--color--primary--default, #fff);
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		margin-bottom: var(--pf-t--global--spacer--md, 16px);
	}

	.group-section__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--pf-t--global--spacer--md, 16px) var(--pf-t--global--spacer--lg, 24px);
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.group-section__body {
		padding: var(--pf-t--global--spacer--md, 16px) var(--pf-t--global--spacer--lg, 24px);
	}

	.group-section :global(.group-empty) {
		text-align: center;
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		padding: var(--pf-t--global--spacer--lg, 24px) 0;
		margin: 0;
	}
</style>
