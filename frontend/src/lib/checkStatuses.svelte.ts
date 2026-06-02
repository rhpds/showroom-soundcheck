import { getWorkshopCheckStatuses, createSession } from '$lib/api';
import type { WorkshopCheckStatusMap, CheckSessionStatus } from '$lib/types';

export function checkStatusColor(status: CheckSessionStatus): string {
	switch (status) {
		case 'completed': return 'green';
		case 'running': case 'pending': return 'blue';
		case 'failed': return 'red';
	}
}

export function checkStatusLabel(status: CheckSessionStatus): string {
	switch (status) {
		case 'completed': return 'Passed';
		case 'running': return 'Running';
		case 'pending': return 'Pending';
		case 'failed': return 'Failed';
	}
}

export function createCheckStatusManager(getWorkshopIds: () => string[]) {
	let statuses = $state.raw<WorkshopCheckStatusMap>({});
	let running = $state(new Set<string>());
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	async function load() {
		const ids = getWorkshopIds();
		if (ids.length === 0) return;
		try {
			statuses = await getWorkshopCheckStatuses(ids);
		} catch (e) {
			console.warn('Failed to load check statuses:', e);
		}

		const hasInFlight =
			running.size > 0 ||
			Object.values(statuses).some(
				(s) => s && (s.status === 'running' || s.status === 'pending')
			);
		if (hasInFlight && !pollTimer) {
			pollTimer = setInterval(load, 10000);
		} else if (!hasInFlight && pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
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
			statuses = {
				...statuses,
				[workshopId]: {
					status: 'pending',
					session_id: result.session_id,
					created_at: new Date().toISOString()
				}
			};
		} catch (e) {
			errorMsg = e instanceof Error ? e.message : 'Failed to run check';
		}

		const done = new Set(running);
		done.delete(workshopId);
		running = done;

		if (!pollTimer) {
			pollTimer = setInterval(load, 10000);
		}
		return errorMsg;
	}

	function destroy() {
		if (pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	return {
		get statuses() { return statuses; },
		get running() { return running; },
		load,
		run,
		destroy
	};
}
