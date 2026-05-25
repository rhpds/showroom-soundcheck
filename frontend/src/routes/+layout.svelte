<script lang="ts">
	import { onMount } from 'svelte';
	import Sidebar from '$lib/components/Sidebar.svelte';

	let sidebarOpen = $state(false);
	let sidebarCollapsed = $state(false);
	let isMobile = $state(false);

	const { children } = $props();

	onMount(() => {
		const lgQuery = window.matchMedia('(min-width: 1200px)');
		const mobileQuery = window.matchMedia('(max-width: 767px)');

		function update() {
			isMobile = mobileQuery.matches;
			sidebarCollapsed = !lgQuery.matches;
			if (lgQuery.matches) sidebarOpen = true;
			else sidebarOpen = false;
		}

		update();
		lgQuery.addEventListener('change', update);
		mobileQuery.addEventListener('change', update);

		return () => {
			lgQuery.removeEventListener('change', update);
			mobileQuery.removeEventListener('change', update);
		};
	});

	function toggleSidebar() {
		sidebarOpen = !sidebarOpen;
	}

	function closeSidebar() {
		if (sidebarCollapsed) sidebarOpen = false;
	}
</script>

<a class="skip-to-main" href="#main-content">Skip to main content</a>

<div class="pf-v6-c-page">
	<header class="pf-v6-c-masthead">
		<div class="pf-v6-c-masthead__main">
			{#if sidebarCollapsed}
				<div class="pf-v6-c-masthead__toggle">
					<button
						class="pf-v6-c-button pf-m-plain"
						aria-label="Toggle navigation"
						aria-expanded={sidebarOpen}
						onclick={toggleSidebar}
					>
						<svg viewBox="0 0 16 16" width="18" height="18" fill="currentColor" aria-hidden="true">
							<path d="M1 3h14v1.5H1zm0 4.25h14v1.5H1zm0 4.25h14V13H1z" />
						</svg>
					</button>
				</div>
			{/if}
			<div class="pf-v6-c-masthead__brand">
				<a class="pf-v6-c-masthead__logo" href="/">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 32 32"
						width="28"
						height="28"
						aria-hidden="true"
					>
						<circle cx="16" cy="16" r="15" fill="#3b82f6" />
						<polyline
							points="4,16 9,16 12,16 14,7 16,24 18,11 20,16 23,16 28,16"
							fill="none"
							stroke="white"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						/>
					</svg>
					Soundcheck
				</a>
			</div>
		</div>
	</header>

	{#if isMobile && sidebarOpen}
		<div class="sidebar-overlay" role="presentation" onclick={closeSidebar}></div>
	{/if}

	<div
		class="pf-v6-c-page__sidebar"
		class:pf-m-expanded={sidebarOpen}
		class:pf-m-collapsed={!sidebarOpen}
		class:sidebar-mobile-open={isMobile && sidebarOpen}
	>
		<div class="pf-v6-c-page__sidebar-main">
			{#if isMobile && sidebarOpen}
				<div class="sidebar-mobile-header">
					<span class="sidebar-mobile-title">Soundcheck</span>
					<button
						class="pf-v6-c-button pf-m-plain"
						aria-label="Close navigation"
						onclick={closeSidebar}
					>
						<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true">
							<path d="M12.5 3.5L8 8l4.5 4.5-1 1L7 9l-4.5 4.5-1-1L6 8 1.5 3.5l1-1L7 7l4.5-4.5z" />
						</svg>
					</button>
				</div>
			{/if}
			<div class="pf-v6-c-page__sidebar-body">
				<Sidebar onNavigate={closeSidebar} />
			</div>
		</div>
	</div>

	<div class="pf-v6-c-page__main-container">
		<main class="pf-v6-c-page__main" id="main-content" tabindex="-1">
			<section class="pf-v6-c-page__main-section">
				{@render children()}
			</section>
		</main>
	</div>
</div>

<style>
	:global(.pf-v6-c-masthead__logo) {
		color: inherit;
		text-decoration: none;
		font-weight: 700;
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}

	:global(.pf-v6-c-masthead) {
		position: sticky;
		top: 0;
		z-index: 200;
	}

	@media (max-width: 767px) {
		:global(.pf-v6-c-page__sidebar.pf-m-collapsed) {
			display: none !important;
		}
	}

	.skip-to-main {
		position: absolute;
		left: -10000px;
		top: auto;
		width: 1px;
		height: 1px;
		overflow: hidden;
		z-index: 1000;
		padding: 8px 16px;
		background: var(--pf-t--global--color--brand--default, #0066cc);
		color: #fff;
		text-decoration: none;
		font-weight: 600;
		border-radius: 0 0 4px 0;
	}
	.skip-to-main:focus {
		position: fixed;
		left: 0;
		top: 0;
		width: auto;
		height: auto;
		overflow: visible;
	}

	.sidebar-overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		z-index: 299;
	}

	.sidebar-mobile-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 16px;
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.sidebar-mobile-title {
		font-weight: 700;
		font-size: 1rem;
	}

	:global(.sidebar-mobile-open) {
		position: fixed !important;
		top: 0;
		left: 0;
		bottom: 0;
		width: 280px;
		z-index: 300 !important;
		transform: translateX(0) !important;
		visibility: visible !important;
		overflow-y: auto;
		background: var(--pf-t--global--background--color--secondary--default, #fff);
	}
</style>
