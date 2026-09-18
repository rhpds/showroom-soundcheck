import { getWorkshopCheckStatuses, createSession, sessionStream } from '$lib/api';
import type { WorkshopCheckStatusMap, CheckSessionStatus } from '$lib/types';

export function checkStatusColor(status: CheckSessionStatus): string {
	switch (status) {
		case 'completed':
			return 'green';
		case 'running':
		case 'pending':
			return 'blue';
		case 'failed':
			return 'red';
	}
}

export function checkStatusLabel(status: CheckSessionStatus): string {
	switch (status) {
		case 'completed':
			return 'Passed';
		case 'running':
			return 'Running';
		case 'pending':
			return 'Pending';
		case 'failed':
			return 'Failed';
	}
}

const MAX_RETRIES = 5;

export function createCheckStatusManager(getWorkshopIds: () => string[]) {
	let statuses = $state.raw<WorkshopCheckStatusMap>({});
	let running = $state.raw(new Set<string>());

	// One EventSource per workshop with an in-flight (pending/running) check,
	// keyed by workshop id, so progress is pushed via SSE (matching the
	// backend's SAQ -> Redis Pub/Sub -> SSE design) instead of polled via
	// REST on a timer.
	const streams = new Map<string, EventSource>();
	const retryTimers = new Map<string, ReturnType<typeof setTimeout>>();
	const retryCounts = new Map<string, number>();

	function closeStream(workshopId: string) {
		streams.get(workshopId)?.close();
		streams.delete(workshopId);
		const timer = retryTimers.get(workshopId);
		if (timer) {
			clearTimeout(timer);
			retryTimers.delete(workshopId);
		}
		retryCounts.delete(workshopId);
	}

	function applyUpdate(
		workshopId: string,
		sessionId: string,
		status: CheckSessionStatus,
		createdAt: string
	) {
		statuses = {
			...statuses,
			[workshopId]: { status, session_id: sessionId, created_at: createdAt }
		};
	}

	function watchSession(workshopId: string, sessionId: string, createdAt: string) {
		closeStream(workshopId);
		const es = sessionStream(sessionId);
		streams.set(workshopId, es);

		function handleMessage(event: MessageEvent) {
			try {
				const update = JSON.parse(event.data);
				const status = update?.session?.status as CheckSessionStatus | undefined;
				if (status) applyUpdate(workshopId, sessionId, status, createdAt);
			} catch (e) {
				console.error('Failed to parse check-status SSE message', e);
			}
		}

		es.addEventListener('session_update', handleMessage);
		es.addEventListener('session_complete', (event) => {
			handleMessage(event as MessageEvent);
			closeStream(workshopId);
		});

		es.onerror = () => {
			closeStream(workshopId);
			const entry = statuses[workshopId];
			if (entry?.status === 'completed' || entry?.status === 'failed') return;

			const attempt = (retryCounts.get(workshopId) ?? 0) + 1;
			if (attempt > MAX_RETRIES) return; // give up; the next load() (manual refresh) will pick up the final state
			retryCounts.set(workshopId, attempt);
			const jitter = Math.random() * 1000;
			const delay = Math.min(1000 * 2 ** attempt + jitter, 30000);
			const timer = setTimeout(async () => {
				retryTimers.delete(workshopId);
				try {
					const fresh = await getWorkshopCheckStatuses([workshopId]);
					const freshEntry = fresh[workshopId];
					if (freshEntry) {
						statuses = { ...statuses, [workshopId]: freshEntry };
						if (freshEntry.status === 'completed' || freshEntry.status === 'failed') return;
					}
				} catch (e) {
					console.warn('Failed to refresh check status:', e);
				}
				watchSession(workshopId, sessionId, createdAt);
			}, delay);
			retryTimers.set(workshopId, timer);
		};
	}

	async function load() {
		const ids = getWorkshopIds();
		if (ids.length === 0) return;
		try {
			statuses = await getWorkshopCheckStatuses(ids);
		} catch (e) {
			console.warn('Failed to load check statuses:', e);
			return;
		}

		// Pick up any in-flight checks (started before this page loaded, from
		// a previous run() call, or from another browser tab) that we aren't
		// already streaming.
		for (const id of ids) {
			const entry = statuses[id];
			if (entry && (entry.status === 'pending' || entry.status === 'running') && !streams.has(id)) {
				watchSession(id, entry.session_id, entry.created_at);
			}
		}

		// Stop watching workshops that are no longer visible (e.g. filtered out).
		const visible = new Set(ids);
		for (const id of streams.keys()) {
			if (!visible.has(id)) closeStream(id);
		}
	}

	async function run(
		workshopId: string,
		cluster: string,
		displayName: string
	): Promise<string | null> {
		if (!workshopId || running.has(workshopId)) return null;
		running = new Set([...running, workshopId]);

		let errorMsg: string | null = null;
		try {
			const result = await createSession({
				workshop_guids: [workshopId],
				babylon_cluster: cluster,
				name: displayName
			});
			const createdAt = new Date().toISOString();
			applyUpdate(workshopId, result.session_id, 'pending', createdAt);
			watchSession(workshopId, result.session_id, createdAt);
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : 'Failed to run check';
		}

		const done = new Set(running);
		done.delete(workshopId);
		running = done;

		return errorMsg;
	}

	function destroy() {
		for (const id of [...streams.keys()]) closeStream(id);
	}

	return {
		get statuses() {
			return statuses;
		},
		get running() {
			return running;
		},
		load,
		run,
		destroy
	};
}
