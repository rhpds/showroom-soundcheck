<script lang="ts">
	let {
		headers,
		rows = 5
	}: {
		headers: string[];
		rows?: number;
	} = $props();

	const widths = [
		[85, 60, 45, 70, 55],
		[70, 50, 65, 40, 80],
		[90, 45, 55, 60, 50],
		[60, 75, 40, 85, 65],
		[75, 55, 70, 50, 45]
	];
</script>

<div role="status" aria-label="Loading">
	<table class="pf-v6-c-table pf-m-grid-md" role="grid">
		<thead class="pf-v6-c-table__thead">
			<tr class="pf-v6-c-table__tr">
				<th class="pf-v6-c-table__th col-pin" aria-label="Pin"></th>
				{#each headers as header}
					<th class="pf-v6-c-table__th">{header}</th>
				{/each}
				<th class="pf-v6-c-table__th col-actions" aria-label="Actions"></th>
			</tr>
		</thead>
		<tbody class="pf-v6-c-table__tbody">
			{#each { length: rows } as _, row}
				{@const w = widths[row % widths.length]}
				<tr class="pf-v6-c-table__tr">
					<td class="pf-v6-c-table__td col-pin">
						<div
							class="pf-v6-c-skeleton pf-m-circle"
							style="--pf-v6-c-skeleton--Width: 14px; --pf-v6-c-skeleton--Height: 14px"
						></div>
					</td>
					{#each headers as _, col}
						<td class="pf-v6-c-table__td">
							<div
								class="pf-v6-c-skeleton pf-m-text-sm"
								style="--pf-v6-c-skeleton--Width: {w[col % w.length]}%"
							></div>
						</td>
					{/each}
					<td class="pf-v6-c-table__td col-actions">
						<div
							class="pf-v6-c-skeleton pf-m-circle"
							style="--pf-v6-c-skeleton--Width: 14px; --pf-v6-c-skeleton--Height: 14px"
						></div>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
