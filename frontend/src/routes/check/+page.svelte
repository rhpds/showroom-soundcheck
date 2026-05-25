<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { checkRedirect } from '$lib/api';
	import Spinner from '$lib/components/Spinner.svelte';

	let error = $state('');

	onMount(async () => {
		const params = page.url.searchParams;
		if (
			!params.has('urls') &&
			!params.has('guid') &&
			!params.has('workshop') &&
			!params.has('pool')
		) {
			goto('/');
			return;
		}
		try {
			const sessionId = await checkRedirect(params);
			goto(sessionId ? `/session/${sessionId}` : '/');
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to create session';
		}
	});
</script>

{#if error}
	<div
		class="pf-v6-u-text-align-center pf-v6-u-mt-2xl"
		style="max-width: 480px; margin-left: auto; margin-right: auto;"
	>
		<div class="pf-v6-c-alert pf-m-danger pf-m-inline pf-v6-u-mb-md" role="alert">
			<div class="pf-v6-c-alert__icon">
				<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true"
					><path
						d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
					/></svg
				>
			</div>
			<h4 class="pf-v6-c-alert__title">{error}</h4>
		</div>
		<a href="/" class="pf-v6-c-button pf-m-primary">Go Home</a>
	</div>
{:else}
	<div class="pf-v6-u-text-align-center pf-v6-u-mt-2xl">
		<Spinner label="Creating session" />
		<p class="pf-v6-u-mt-md">Creating session...</p>
	</div>
{/if}
