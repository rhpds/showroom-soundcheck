<script lang="ts">
	let { label = 'Loading', size }: { label?: string; size?: 'sm' | 'md' | 'lg' | 'xl' } = $props();
</script>

<span class="pf-v6-c-spinner {size ? `pf-m-${size}` : ''}" role="progressbar" aria-label={label}>
	<span class="pf-v6-c-spinner__clipper"></span>
	<span class="pf-v6-c-spinner__lead-ball"></span>
	<span class="pf-v6-c-spinner__tail-ball"></span>
</span>
