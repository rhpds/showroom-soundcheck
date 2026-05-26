<script lang="ts">
	import StatusBadge from './StatusBadge.svelte';
	import Modal from './Modal.svelte';
	import type { TargetPublic, CheckResultPublic, TabDetail, ContentPageDetail } from '$lib/types';

	let {
		target,
		result,
		onClose
	}: {
		target: TargetPublic | null;
		result: CheckResultPublic | null;
		onClose: () => void;
	} = $props();

	let copiedField = $state<string | null>(null);

	async function copyToClipboard(text: string, field: string) {
		try {
			await navigator.clipboard.writeText(text);
			copiedField = field;
			setTimeout(() => {
				copiedField = null;
			}, 1500);
	} catch (e) {
		console.warn('Clipboard write failed:', e);
	}
	}

	let detail = $derived(result?.detail ?? null);
	let tabs = $derived<TabDetail[]>(
		detail &&
			!('legacy' in detail && detail.legacy) &&
			'tabs' in detail &&
			Array.isArray(detail.tabs)
			? detail.tabs
			: []
	);
	let contentPages = $derived<ContentPageDetail[]>(
		detail &&
			!('legacy' in detail && detail.legacy) &&
			'content_pages' in detail &&
			Array.isArray(detail.content_pages)
			? detail.content_pages
			: []
	);
	let isLegacy = $derived(!!(detail && 'legacy' in detail && detail.legacy));
</script>

{#if target}
	<Modal title="Target Details" {onClose}>
		<div class="td">
			<div class="td__header">
				<StatusBadge status={target.status} />
				<span class="td__label">{target.label || target.url}</span>
			</div>

			{#if target.url}
				<div class="td__url">
					<a href={target.url} target="_blank" rel="noopener noreferrer" class="td__url-link"
						>{target.url}</a
					>
					<button
						class="pf-v6-c-button pf-m-plain pf-m-sm"
						aria-label="Copy URL"
						onclick={() => copyToClipboard(target?.url ?? '', 'url')}
						>{#if copiedField === 'url'}<svg
								viewBox="0 0 16 16"
								width="14"
								height="14"
								fill="currentColor"
								><path
									d="M13.36 4.65a.5.5 0 0 0-.72-.02L7.2 8.94 5.35 7.17a.5.5 0 1 0-.7.71l2.2 2.12a.5.5 0 0 0 .7-.01l3.8-3.63a.5.5 0 0 0 .01-.71l1.96-1.71Z"
								/></svg
							>{:else}<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"
								><path
									d="M5 2a1 1 0 0 0-1 1v1H3a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1v-1h1a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1H5Zm5 9H3V5h1v6a1 1 0 0 0 1 1h5v1Zm2-2H5V3h7v6Z"
								/></svg
							>{/if}</button
					>
				</div>
			{/if}

			<div class="td__labels">
				{#if target.guid}
					<span class="td__guid-badge td__guid-badge--purple">GUID: {target.guid}</span>
					<button
						class="td__copy"
						aria-label="Copy GUID"
						onclick={() => copyToClipboard(target?.guid ?? '', 'guid')}
					>
						{#if copiedField === 'guid'}<svg
								viewBox="0 0 16 16"
								width="12"
								height="12"
								fill="currentColor"
								><path
									d="M13.36 4.65a.5.5 0 0 0-.72-.02L7.2 8.94 5.35 7.17a.5.5 0 1 0-.7.71l2.2 2.12a.5.5 0 0 0 .7-.01l3.8-3.63a.5.5 0 0 0 .01-.71l1.96-1.71Z"
								/></svg
							> Copied{:else}<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"
								><path
									d="M5 2a1 1 0 0 0-1 1v1H3a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1v-1h1a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1H5Zm5 9H3V5h1v6a1 1 0 0 0 1 1h5v1Zm2-2H5V3h7v6Z"
								/></svg
							> Copy{/if}
					</button>
				{/if}
				{#if target.workshop_guid}
					<span class="td__guid-badge td__guid-badge--blue">Workshop: {target.workshop_guid}</span>
					<button
						class="td__copy"
						aria-label="Copy Workshop GUID"
						onclick={() => copyToClipboard(target?.workshop_guid ?? '', 'workshop')}
					>
						{#if copiedField === 'workshop'}<svg
								viewBox="0 0 16 16"
								width="12"
								height="12"
								fill="currentColor"
								><path
									d="M13.36 4.65a.5.5 0 0 0-.72-.02L7.2 8.94 5.35 7.17a.5.5 0 1 0-.7.71l2.2 2.12a.5.5 0 0 0 .7-.01l3.8-3.63a.5.5 0 0 0 .01-.71l1.96-1.71Z"
								/></svg
							> Copied{:else}<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"
								><path
									d="M5 2a1 1 0 0 0-1 1v1H3a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1v-1h1a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1H5Zm5 9H3V5h1v6a1 1 0 0 0 1 1h5v1Zm2-2H5V3h7v6Z"
								/></svg
							> Copy{/if}
					</button>
				{/if}
				{#if target.tier_used}
					<span class="pf-v6-c-label pf-m-compact"
						><span class="pf-v6-c-label__content"
							><span class="pf-v6-c-label__text">Tier {target.tier_used}</span></span
						></span
					>
				{/if}
				{#if target.response_time_ms}
					<span class="pf-v6-c-label pf-m-compact"
						><span class="pf-v6-c-label__content"
							><span class="pf-v6-c-label__text">{target.response_time_ms}ms</span></span
						></span
					>
				{/if}
			</div>

			{#if target.error_message}
				<div class="pf-v6-c-alert pf-m-danger pf-m-inline td__error">
					<div class="pf-v6-c-alert__icon">
						<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true"
							><path
								d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
							/></svg
						>
					</div>
					<h4 class="pf-v6-c-alert__title">Error</h4>
					<div class="pf-v6-c-alert__description td__error-message">{target.error_message}</div>
				</div>
			{/if}

			{#if detail}
				<div class="td__detail">
					<h3 class="td__detail-title">
						{isLegacy ? 'Legacy Check Detail' : 'Readyz Check Detail'}
					</h3>

					{#if contentPages.length > 0}
						<h4 class="td__section-title">Content</h4>
						<ul class="td__list" role="list">
							{#each contentPages as cp}
								<li class="td__list-item" role="listitem">
									<div class="td__list-row">
										<span
											class="td__status-icon"
											class:td__status-icon--ok={cp.reachable}
											class:td__status-icon--fail={!cp.reachable}
										>
											{#if cp.reachable}
												<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
													><path
														d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm3.36 4.65a.5.5 0 0 0-.72-.02L7.2 8.94 5.35 7.17a.5.5 0 1 0-.7.71l2.2 2.12a.5.5 0 0 0 .7-.01l3.8-3.63a.5.5 0 0 0 .01-.71Z"
													/></svg
												>
											{:else}
												<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
													><path
														d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm2.35 4.65a.5.5 0 0 0-.7 0L8 7.29 6.35 5.65a.5.5 0 1 0-.7.7L7.29 8 5.65 9.65a.5.5 0 1 0 .7.7L8 8.71l1.65 1.64a.5.5 0 0 0 .7-.7L8.71 8l1.64-1.65a.5.5 0 0 0 0-.7Z"
													/></svg
												>
											{/if}
										</span>
										<span class="td__list-name">{cp.name}</span>
										{#if cp.status_code}
											<span
												class="pf-v6-c-label pf-m-compact {cp.status_code >= 200 &&
												cp.status_code < 400
													? 'pf-m-green'
													: 'pf-m-red'}"
											>
												<span class="pf-v6-c-label__content"
													><span class="pf-v6-c-label__text">{cp.status_code}</span></span
												>
											</span>
										{/if}
									</div>
									{#if cp.url}
										<div class="td__list-sub">{cp.url}</div>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}

					{#if tabs.length > 0}
						<h4 class="td__section-title">Endpoints / Tabs</h4>
						<ul class="td__list" role="list">
							{#each tabs as tab}
								<li
									class="td__list-item"
									class:td__list-item--muted={tab.initial_state === 'deferred' || tab.initial_state === 'skip'}
									role="listitem"
								>
									<div class="td__list-row">
										{#if tab.initial_state === 'skip'}
											<span class="td__status-icon td__status-icon--skip" title="skipped">
												<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
													><path
														d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm0 1.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM5 8a.5.5 0 0 1 .5-.5h5a.5.5 0 0 1 0 1h-5A.5.5 0 0 1 5 8Z"
													/></svg
												>
											</span>
										{:else if tab.initial_state === 'deferred' && !tab.reachable}
											<span class="td__status-icon td__status-icon--deferred" title="deferred">
												<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
													><path
														d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm0 1.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM8 4a.5.5 0 0 1 .5.5V8h2a.5.5 0 0 1 0 1H8a.5.5 0 0 1-.5-.5v-4A.5.5 0 0 1 8 4Z"
													/></svg
												>
											</span>
										{:else}
											<span
												class="td__status-icon"
												class:td__status-icon--ok={tab.reachable}
												class:td__status-icon--fail={!tab.reachable}
											>
												{#if tab.reachable}
													<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
														><path
															d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm3.36 4.65a.5.5 0 0 0-.72-.02L7.2 8.94 5.35 7.17a.5.5 0 1 0-.7.71l2.2 2.12a.5.5 0 0 0 .7-.01l3.8-3.63a.5.5 0 0 0 .01-.71Z"
														/></svg
													>
												{:else}
													<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
														><path
															d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1Zm2.35 4.65a.5.5 0 0 0-.7 0L8 7.29 6.35 5.65a.5.5 0 1 0-.7.7L7.29 8 5.65 9.65a.5.5 0 1 0 .7.7L8 8.71l1.65 1.64a.5.5 0 0 0 .7-.7L8.71 8l1.64-1.65a.5.5 0 0 0 0-.7Z"
														/></svg
													>
												{/if}
											</span>
										{/if}
										<span class="td__list-name">{tab.name}</span>
										<div class="td__list-badges">
											{#if tab.initial_state === 'skip'}
												<span class="pf-v6-c-label pf-m-compact">
													<span class="pf-v6-c-label__content"
														><span class="pf-v6-c-label__text">skip</span></span
													>
												</span>
											{:else if tab.initial_state === 'deferred'}
												<span class="pf-v6-c-label pf-m-compact pf-m-blue">
													<span class="pf-v6-c-label__content"
														><span class="pf-v6-c-label__text">deferred</span></span
													>
												</span>
											{/if}
											{#if tab.status_code}
												<span
													class="pf-v6-c-label pf-m-compact {tab.status_code >= 200 &&
													tab.status_code < 400
														? 'pf-m-green'
														: tab.initial_state === 'deferred'
															? ''
															: 'pf-m-red'}"
												>
													<span class="pf-v6-c-label__content"
														><span class="pf-v6-c-label__text">{tab.status_code}</span></span
													>
												</span>
											{/if}
											{#if tab.iframe_blocked}
												<span
													class="td__icon-indicator td__icon-indicator--warn"
													title="iframe blocked"
												>
													<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
														><path
															d="M2 3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H9.5l.5 1.5h1a.5.5 0 0 1 0 1h-6a.5.5 0 0 1 0-1h1L6.5 12H3a1 1 0 0 1-1-1V3Zm1.5.5v6h9v-6h-9ZM8.9 7.4l1.45-1.75a.4.4 0 0 0-.05-.56.4.4 0 0 0-.55.05L8 7.22 6.25 5.14a.4.4 0 0 0-.55-.05.4.4 0 0 0-.05.56L7.1 7.4 5.65 9.15a.4.4 0 0 0 .05.56.4.4 0 0 0 .55-.05L8 7.58l1.75 2.08a.4.4 0 0 0 .55.05.4.4 0 0 0 .05-.56L8.9 7.4Z"
														/></svg
													>
												</span>
											{/if}
											{#if tab.external}
												<span
													class="td__icon-indicator td__icon-indicator--muted"
													title="external link"
												>
													<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"
														><path
															d="M9 2.5a.5.5 0 0 1 .5-.5H13a.5.5 0 0 1 .5.5V6a.5.5 0 0 1-1 0V3.71L8.35 7.85a.5.5 0 1 1-.7-.7L11.79 3H9.5a.5.5 0 0 1-.5-.5ZM3.5 4A1.5 1.5 0 0 0 2 5.5v7A1.5 1.5 0 0 0 3.5 14h7a1.5 1.5 0 0 0 1.5-1.5V9a.5.5 0 0 0-1 0v3.5a.5.5 0 0 1-.5.5h-7a.5.5 0 0 1-.5-.5v-7a.5.5 0 0 1 .5-.5H7a.5.5 0 0 0 0-1H3.5Z"
														/></svg
													>
												</span>
											{/if}
										</div>
									</div>
									{#if tab.url}
										<div class="td__list-sub">{tab.url}</div>
									{/if}
									{#if tab.error && tab.initial_state !== 'skip'}
										<div
											class={tab.initial_state === 'deferred'
												? 'td__list-sub'
												: 'td__list-error'}
										>
											{tab.error}
										</div>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/if}
		</div>
	</Modal>
{/if}

<style>
	.td__header {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}

	.td__label {
		font-weight: 600;
		font-size: var(--pf-t--global--font--size--lg, 1.125rem);
		word-break: break-all;
		min-width: 0;
	}

	.td__url {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 12px;
		padding: 8px 12px;
		background: var(--pf-t--global--background--color--secondary--default, #f0f0f0);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
	}

	.td__url-link {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
		flex: 1;
	}

	.td__labels {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
		margin-bottom: 16px;
	}

	.td__guid-badge {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: 12px;
		font-size: 0.75rem;
		font-weight: 500;
		white-space: nowrap;
		border: 1px solid;
	}

	.td__guid-badge--purple {
		color: #3b1f6e;
		background: #f2e6ff;
		border-color: #c9a0ff;
	}

	.td__guid-badge--blue {
		color: #003d73;
		background: #e7f1fa;
		border-color: #73bcf7;
	}

	.td__copy {
		background: none;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		padding: 2px 8px;
		font-size: var(--pf-t--global--font--size--xs, 0.75rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		cursor: pointer;
		white-space: nowrap;
		transition: background-color 0.1s ease;
	}

	.td__copy:hover {
		background: var(--pf-t--global--background--color--secondary--default, #f0f0f0);
	}

	.td__error {
		margin-bottom: 16px;
	}

	.td__error-message {
		white-space: pre-wrap;
	}

	.td__detail {
		border-top: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		padding-top: 16px;
	}

	.td__detail-title {
		font-size: var(--pf-t--global--font--size--md, 1rem);
		font-weight: 600;
		margin: 0 0 16px;
	}

	.td__section-title {
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		font-weight: 600;
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		text-transform: uppercase;
		letter-spacing: 0.03em;
		margin: 0 0 8px;
	}

	.td__list {
		list-style: none;
		padding: 0;
		margin: 0 0 16px;
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
	}

	.td__list-item {
		padding: 10px 12px;
		border-bottom: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.td__list-item:last-child {
		border-bottom: none;
	}

	.td__list-row {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.td__status-icon {
		flex-shrink: 0;
		width: 18px;
		height: 18px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
	}

	.td__status-icon :global(svg) {
		width: 100%;
		height: 100%;
	}

	.td__status-icon--ok {
		color: var(--pf-t--global--color--status--success--default, #3e8635);
	}

	.td__status-icon--fail {
		color: var(--pf-t--global--color--status--danger--default, #c9190b);
	}

	.td__status-icon--deferred {
		color: var(--pf-t--global--color--status--info--default, #2b9af3);
	}

	.td__status-icon--skip {
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
	}

	.td__list-item--muted {
		opacity: 0.7;
	}

	.td__list-name {
		flex: 1;
		min-width: 0;
		word-break: break-word;
	}

	.td__list-badges {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-shrink: 0;
	}

	.td__icon-indicator {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		border-radius: 4px;
		padding: 2px;
	}

	.td__icon-indicator :global(svg) {
		width: 100%;
		height: 100%;
	}

	.td__icon-indicator--warn {
		color: #795600;
		background: #fef6e6;
	}

	.td__icon-indicator--muted {
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		background: var(--pf-t--global--background--color--secondary--default, #f0f0f0);
	}

	.td__list-sub {
		margin-top: 4px;
		padding-left: 24px;
		font-size: var(--pf-t--global--font--size--xs, 0.75rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.td__list-error {
		margin-top: 4px;
		padding-left: 24px;
		font-size: var(--pf-t--global--font--size--xs, 0.75rem);
		color: var(--pf-t--global--color--status--danger--default, #c9190b);
	}
</style>
