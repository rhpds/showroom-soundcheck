<script lang="ts">
	import { page } from '$app/state';

	let { onNavigate = () => {} }: { onNavigate?: () => void } = $props();

	let currentPath = $derived(page.url.pathname);

	function isActive(href: string): boolean {
		if (href === '/sessions') return currentPath.startsWith('/session');
		if (href === '/groups') return currentPath.startsWith('/group');
		return false;
	}
</script>

<nav class="pf-v6-c-nav" aria-label="Main navigation" data-sveltekit-preload-data="hover">
	<div class="pf-v6-c-nav__main-body">
		<ul class="pf-v6-c-nav__list">
			<li class="pf-v6-c-nav__item">
				<a
					class="pf-v6-c-nav__link"
					class:pf-m-current={isActive('/sessions')}
					href="/sessions"
					aria-current={isActive('/sessions') ? 'page' : undefined}
					onclick={() => onNavigate()}
				>
					<span class="pf-v6-c-nav__link-text">Sessions</span>
				</a>
			</li>
			<li class="pf-v6-c-nav__item">
				<a
					class="pf-v6-c-nav__link"
					class:pf-m-current={isActive('/groups')}
					href="/groups"
					aria-current={isActive('/groups') ? 'page' : undefined}
					onclick={() => onNavigate()}
				>
					<span class="pf-v6-c-nav__link-text">Groups</span>
				</a>
			</li>
		</ul>
	</div>
</nav>
