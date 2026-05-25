<script lang="ts">
	import StatusBadge from './StatusBadge.svelte';
	import type { GroupRunPublic, SessionListItem, TargetPublic } from '$lib/types';

	let {
		runs,
		runSessions,
		targetsBySession,
		onPreview
	}: {
		runs: GroupRunPublic[];
		runSessions: Record<string, SessionListItem[]>;
		targetsBySession: Record<string, TargetPublic[]>;
		onPreview: (sessionId: string) => void;
	} = $props();

	let expandedRuns = $state.raw<Set<string>>(new Set());

	function toggleRun(runId: string) {
		const next = new Set(expandedRuns);
		if (next.has(runId)) next.delete(runId);
		else next.add(runId);
		expandedRuns = next;
	}
</script>

<div class="group-section">
	<div class="group-section__header">
		<h2 class="pf-v6-c-title pf-m-lg">Run History</h2>
	</div>
	<div class="group-section__body">
		{#if runs.length === 0}
			<p class="group-empty">No checks run yet.</p>
		{:else}
			<div class="run-list">
				{#each runs as run}
					{@const sessions = runSessions[run.run_id] || []}
					<div class="run-list__item" class:run-list__item--expanded={expandedRuns.has(run.run_id)}>
						<button class="run-list__toggle" onclick={() => toggleRun(run.run_id)}>
							<div class="run-list__toggle-left">
								<StatusBadge status={run.status} size="sm" />
								<span>{sessions.length} session{sessions.length !== 1 ? 's' : ''}</span>
								<span class="run-list__date">{new Date(run.created_at).toLocaleString()}</span>
							</div>
							<span class="run-list__chevron">
								{#if expandedRuns.has(run.run_id)}
									<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"
										><path d="M3 6l5 5 5-5H3Z" /></svg
									>
								{:else}
									<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"
										><path d="M6 3l5 5-5 5V3Z" /></svg
									>
								{/if}
							</span>
						</button>
						{#if expandedRuns.has(run.run_id)}
							<div class="run-list__sessions">
								{#each sessions as cs}
									{@const sessionTargets = targetsBySession[cs.session_id] || []}
									{@const healthy = sessionTargets.filter((t) => t.status === 'healthy').length}
									<div
										class="run-list__session"
										onclick={() => onPreview(cs.session_id)}
										onkeydown={(e) => e.key === 'Enter' && onPreview(cs.session_id)}
										role="button"
										tabindex="0"
									>
										<div class="run-list__session-left">
											<StatusBadge status={cs.status} size="sm" />
											<span>{cs.name || cs.display_label}</span>
										</div>
										<span class="run-list__session-stat"
											>{healthy}/{sessionTargets.length} healthy</span
										>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
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

	.group-empty {
		text-align: center;
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
		padding: var(--pf-t--global--spacer--lg, 24px) 0;
		margin: 0;
	}

	.run-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.run-list__item {
		border: 1px solid var(--pf-t--global--border--color--default, #d2d2d2);
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		overflow: hidden;
	}

	.run-list__item--expanded {
		border-color: var(--pf-t--global--color--brand--default, #0066cc);
	}

	.run-list__toggle {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: 12px 16px;
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
		font: inherit;
		transition: background-color 0.1s ease;
	}

	.run-list__toggle:hover {
		background: var(--pf-t--global--background--color--secondary--default, #f0f0f0);
	}

	.run-list__toggle-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.run-list__date {
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
	}

	.run-list__chevron {
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
	}

	.run-list__sessions {
		padding: 0 16px 12px;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.run-list__session {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 12px;
		border-radius: var(--pf-t--global--border--radius--small, 3px);
		cursor: pointer;
		transition: background-color 0.1s ease;
	}

	.run-list__session:hover {
		background: var(--pf-t--global--background--color--secondary--default, #f0f0f0);
	}

	.run-list__session:focus-visible {
		outline: 2px solid var(--pf-t--global--color--brand--default, #0066cc);
		outline-offset: -2px;
	}

	.run-list__session-left {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.run-list__session-stat {
		font-size: var(--pf-t--global--font--size--sm, 0.875rem);
		color: var(--pf-t--global--text--color--subtle, #6a6e73);
	}
</style>
