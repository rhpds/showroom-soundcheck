<script lang="ts">
	/**
	 * Dual-thumb range slider over a discrete, ordered set of `steps`.
	 *
	 * Because `steps` can be spaced however the caller likes (e.g. denser at
	 * the low end), this gives a "log-scale-like" feel without needing any
	 * exponential math internally — position is just an index into `steps`.
	 *
	 * The top-most step is treated as "uncapped" by callers (e.g. rendered
	 * with a `+` suffix) since it typically represents "this value or more".
	 */
	let {
		steps,
		valueMin = $bindable(),
		valueMax = $bindable(),
		onchange,
		minAriaLabel = 'Minimum value',
		maxAriaLabel = 'Maximum value'
	}: {
		steps: number[];
		valueMin: number;
		valueMax: number;
		onchange?: () => void;
		minAriaLabel?: string;
		maxAriaLabel?: string;
	} = $props();

	const lastIndex = $derived(steps.length - 1);

	function indexOf(value: number): number {
		const idx = steps.indexOf(value);
		return idx === -1 ? 0 : idx;
	}

	let minIndex = $derived(indexOf(valueMin));
	let maxIndex = $derived(indexOf(valueMax));

	let minPercent = $derived(lastIndex === 0 ? 0 : (minIndex / lastIndex) * 100);
	let maxPercent = $derived(lastIndex === 0 ? 100 : (maxIndex / lastIndex) * 100);

	// When the two thumbs are bunched together on the right half, the min
	// thumb needs to render on top so it stays reachable.
	let minOnTop = $derived(minPercent > 50);

	let maxLabel = $derived(maxIndex === lastIndex ? `${steps[maxIndex]}+` : `${steps[maxIndex]}`);
	let minLabel = $derived(`${steps[minIndex]}`);

	function handleMinInput(e: Event) {
		const target = e.currentTarget as HTMLInputElement;
		const idx = Math.min(Number(target.value), maxIndex);
		// The browser updates the native input's DOM value on every key/drag
		// step before this handler runs. If the clamped index doesn't change
		// the reactive `value={minIndex}` binding below is a no-op, so the
		// underlying DOM value must be forced back explicitly or the thumb
		// visually drifts past the clamp point on repeated input.
		target.value = String(idx);
		const next = steps[idx];
		if (next !== valueMin) {
			valueMin = next;
			onchange?.();
		}
	}

	function handleMaxInput(e: Event) {
		const target = e.currentTarget as HTMLInputElement;
		const idx = Math.max(Number(target.value), minIndex);
		target.value = String(idx);
		const next = steps[idx];
		if (next !== valueMax) {
			valueMax = next;
			onchange?.();
		}
	}
</script>

<div class="range-slider">
	<div class="range-slider__track">
		<div
			class="range-slider__fill"
			style="left: {minPercent}%; width: {maxPercent - minPercent}%"
		></div>
	</div>
	<input
		class="range-slider__input"
		class:range-slider__input--top={minOnTop}
		type="range"
		min="0"
		max={lastIndex}
		step="1"
		value={minIndex}
		oninput={handleMinInput}
		aria-label={minAriaLabel}
		aria-valuetext={minLabel}
	/>
	<input
		class="range-slider__input"
		class:range-slider__input--top={!minOnTop}
		type="range"
		min="0"
		max={lastIndex}
		step="1"
		value={maxIndex}
		oninput={handleMaxInput}
		aria-label={maxAriaLabel}
		aria-valuetext={maxLabel}
	/>
</div>
<div class="range-slider__labels">
	<span class="range-slider__label">{minLabel}</span>
	<span class="range-slider__label-sep">&ndash;</span>
	<span class="range-slider__label">{maxLabel}</span>
	<span class="range-slider__label-unit">users</span>
</div>

<style>
	.range-slider {
		position: relative;
		height: 20px;
		width: 160px;
	}

	.range-slider__track {
		position: absolute;
		top: 50%;
		left: 0;
		right: 0;
		height: 4px;
		transform: translateY(-50%);
		border-radius: 2px;
		background: var(--pf-t--global--border--color--default, #d2d2d2);
	}

	.range-slider__fill {
		position: absolute;
		top: 0;
		height: 100%;
		border-radius: 2px;
		background: var(--pf-t--global--color--brand--default, #0066cc);
	}

	.range-slider__input {
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
		height: 20px;
		margin: 0;
		background: transparent;
		pointer-events: none;
		-webkit-appearance: none;
		appearance: none;
		z-index: 2;
	}

	.range-slider__input--top {
		z-index: 3;
	}

	/* Track: transparent, our custom track div renders the visible line */
	.range-slider__input::-webkit-slider-runnable-track {
		-webkit-appearance: none;
		height: 20px;
		background: transparent;
	}

	.range-slider__input::-moz-range-track {
		height: 20px;
		background: transparent;
		border: none;
	}

	/* Thumb: the only part of the input that should capture pointer events */
	.range-slider__input::-webkit-slider-thumb {
		-webkit-appearance: none;
		pointer-events: auto;
		width: 14px;
		height: 14px;
		margin-top: 3px;
		border-radius: 50%;
		background: #fff;
		border: 2px solid var(--pf-t--global--color--brand--default, #0066cc);
		cursor: pointer;
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
	}

	.range-slider__input::-moz-range-thumb {
		pointer-events: auto;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: #fff;
		border: 2px solid var(--pf-t--global--color--brand--default, #0066cc);
		cursor: pointer;
		box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
	}

	.range-slider__input:focus-visible::-webkit-slider-thumb {
		outline: 2px solid var(--pf-t--global--color--brand--default, #0066cc);
		outline-offset: 2px;
	}

	.range-slider__input:focus-visible::-moz-range-thumb {
		outline: 2px solid var(--pf-t--global--color--brand--default, #0066cc);
		outline-offset: 2px;
	}

	.range-slider__labels {
		display: flex;
		align-items: baseline;
		gap: 4px;
		margin-top: 6px;
		font-size: 0.72rem;
		white-space: nowrap;
	}

	.range-slider__label {
		font-weight: 600;
	}

	.range-slider__label-sep {
		opacity: 0.6;
	}

	.range-slider__label-unit {
		opacity: 0.6;
		margin-left: 2px;
	}
</style>
