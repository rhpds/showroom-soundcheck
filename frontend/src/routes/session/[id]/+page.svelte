<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import SessionContent from '$lib/components/SessionContent.svelte';

	let sessionId = $derived(page.params.id ?? '');
</script>

<div class="session-page">
	<nav class="pf-v6-c-breadcrumb" aria-label="Breadcrumb">
		<ol class="pf-v6-c-breadcrumb__list">
			<li class="pf-v6-c-breadcrumb__item">
				<a class="pf-v6-c-breadcrumb__link" href="/sessions">Sessions</a>
			</li>
			<li class="pf-v6-c-breadcrumb__item">
				<span class="pf-v6-c-breadcrumb__item-divider">/</span>
				<span class="pf-v6-c-breadcrumb__link pf-m-current" aria-current="page">
					Session Details
				</span>
			</li>
		</ol>
	</nav>

	<SessionContent {sessionId} onNavigate={(id) => goto(`/session/${id}`)} />
</div>
