<script lang="ts">
	import { page } from '$app/state';

	const statusCode = $derived(page.status);
	const isNotFound = $derived(statusCode === 404);
</script>

<div
	class="pf-v6-u-text-align-center pf-v6-u-mt-2xl"
	style="max-width: 480px; margin-left: auto; margin-right: auto;"
>
	<div class="pf-v6-u-font-size-4xl pf-v6-u-color-200 pf-v6-u-mb-md" aria-hidden="true">
		{isNotFound ? '404' : statusCode || '?'}
	</div>
	<h1 class="pf-v6-c-title pf-m-2xl">
		{isNotFound ? 'Page not found' : 'Something went wrong'}
	</h1>
	<p class="pf-v6-u-color-200 pf-v6-u-mt-md">
		{#if isNotFound}
			The page you're looking for doesn't exist. Check the URL or head back home.
		{:else}
			{page.error?.message ||
				'An unexpected error occurred. Try refreshing or going back to the home page.'}
		{/if}
	</p>
	<div class="pf-v6-u-mt-lg pf-v6-u-display-flex pf-v6-u-justify-content-center pf-v6-u-gap-md">
		<a href="/" class="pf-v6-c-button pf-m-primary">Go Home</a>
		<button class="pf-v6-c-button pf-m-secondary" onclick={() => history.back()}>Go Back</button>
	</div>
</div>
