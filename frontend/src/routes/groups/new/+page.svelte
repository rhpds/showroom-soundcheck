<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { createGroup, getClusters } from '$lib/api';
	import type { CheckType } from '$lib/types';
	import Spinner from '$lib/components/Spinner.svelte';

	let submitting = $state(false);
	let error = $state('');
	let clusters = $state.raw<string[]>([]);
	let errorEl: HTMLDivElement | undefined = $state();

	let groupForm = $state({
		name: '',
		rc_guids: '',
		workshop_guids: '',
		resource_pools: '',
		check_type: 'readyz' as CheckType,
		babylon_cluster: ''
	});

	let showAdvanced = $state(false);

	onMount(async () => {
		try {
			const data = await getClusters();
			clusters = data.clusters;
		} catch (e) {
			console.error('Failed to load clusters', e);
		}
	});

	async function showError(msg: string) {
		error = msg;
		await tick();
		errorEl?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
		errorEl?.focus();
	}

	async function handleSubmit() {
		if (submitting) return;
		submitting = true;
		error = '';

		try {
			const result = await createGroup({
				name: groupForm.name,
				guids: groupForm.rc_guids
					.split('\n')
					.map((g) => g.trim())
					.filter(Boolean),
				workshop_guids: groupForm.workshop_guids
					.split('\n')
					.map((g) => g.trim())
					.filter(Boolean),
				resource_pools: groupForm.resource_pools
					.split('\n')
					.map((p) => p.trim())
					.filter(Boolean),
				check_type: groupForm.check_type,
				babylon_cluster: groupForm.babylon_cluster
			});

			if (result.group_id) {
				goto(`/group/${result.group_id}`);
			}
		} catch (e: unknown) {
			await showError(e instanceof Error ? e.message : String(e));
		} finally {
			submitting = false;
		}
	}
</script>

<div style="max-width: 560px; margin: 0;">
	<div class="pf-v6-u-mb-lg">
		<h1 class="pf-v6-c-title pf-m-2xl">New Group</h1>
		<p class="pf-v6-u-mt-xs pf-v6-u-color-200">
			Create a group to monitor multiple sources with recurring health checks.
		</p>
	</div>

	{#if error}
		<div
			bind:this={errorEl}
			class="pf-v6-c-alert pf-m-danger pf-m-inline pf-v6-u-mb-md"
			role="alert"
			aria-live="assertive"
			tabindex="-1"
		>
			<div class="pf-v6-c-alert__icon">
				<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true"
					><path
						d="M8.58 1.55a.67.67 0 0 0-1.16 0l-6.25 11A.67.67 0 0 0 1.75 14h12.5a.67.67 0 0 0 .58-1.01l-6.25-11ZM8 5.5a.5.5 0 0 1 .5.5v3a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5Zm.56 5.56a.56.56 0 1 1-1.12 0 .56.56 0 0 1 1.12 0Z"
					/></svg
				>
			</div>
			<h4 class="pf-v6-c-alert__title">{error}</h4>
		</div>
	{/if}

	<div class="pf-v6-c-card">
		<div class="pf-v6-c-card__body">
			<form
				onsubmit={(e) => {
					e.preventDefault();
					handleSubmit();
				}}
			>
				<div class="pf-v6-c-form">
					<div class="pf-v6-c-form__group">
						<label class="pf-v6-c-form__label" for="group-name">Group Name</label>
						<span class="pf-v6-c-form-control">
							<input
								type="text"
								id="group-name"
								bind:value={groupForm.name}
								placeholder="e.g. Summit Day 1"
								required
							/>
						</span>
					</div>

					<div class="pf-v6-c-form__group">
						<label class="pf-v6-c-form__label" for="g-guids">ResourceClaim GUIDs</label>
						<span class="pf-v6-c-form-control">
							<textarea id="g-guids" bind:value={groupForm.rc_guids} rows="2"></textarea>
						</span>
						<span class="pf-v6-c-form__helper-text">One per line</span>
					</div>

					<div class="pf-v6-c-form__group">
						<label class="pf-v6-c-form__label" for="g-ws-guids">Workshop GUIDs</label>
						<span class="pf-v6-c-form-control">
							<textarea id="g-ws-guids" bind:value={groupForm.workshop_guids} rows="2"></textarea>
						</span>
						<span class="pf-v6-c-form__helper-text">One per line</span>
					</div>

					<div class="pf-v6-c-form__group">
						<label class="pf-v6-c-form__label" for="g-pools">ResourcePools</label>
						<span class="pf-v6-c-form-control">
							<textarea id="g-pools" bind:value={groupForm.resource_pools} rows="2"></textarea>
						</span>
						<span class="pf-v6-c-form__helper-text">One per line</span>
					</div>

					{#if clusters.length > 0}
						<div class="pf-v6-c-form__group">
							<label class="pf-v6-c-form__label" for="g-cluster">Babylon Cluster</label>
							<span class="pf-v6-c-form-control">
								<select id="g-cluster" bind:value={groupForm.babylon_cluster}>
									<option value="">(auto)</option>
									{#each clusters as c}
										<option value={c}>{c}</option>
									{/each}
								</select>
							</span>
						</div>
					{/if}

				{#if showAdvanced}
					<div class="pf-v6-c-form__group">
						<label class="pf-v6-c-form__label" for="g-check-type">Check Type</label>
						<span class="pf-v6-c-form-control">
							<select id="g-check-type" bind:value={groupForm.check_type}>
								<option value="readyz">readyz (readiness)</option>
								<option value="healthz">healthz (liveness)</option>
							</select>
						</span>
					</div>
				{/if}

					<div class="pf-v6-u-mt-sm">
						<button
							class="pf-v6-c-button pf-m-link pf-m-inline"
							type="button"
							aria-expanded={showAdvanced}
							onclick={() => (showAdvanced = !showAdvanced)}
						>
							{showAdvanced ? '▾ Hide Advanced Settings' : '▸ Show Advanced Settings'}
						</button>
					</div>

					<div class="pf-v6-u-mt-md">
						<button
							class="pf-v6-c-button pf-m-primary pf-m-block"
							type="submit"
							disabled={submitting}
						>
							{#if submitting}
								<span class="pf-v6-u-mr-sm"><Spinner label="Submitting" size="sm" /></span>
								Creating group…
							{:else}
								Create Group
							{/if}
						</button>
					</div>
				</div>
			</form>
		</div>
	</div>
</div>
