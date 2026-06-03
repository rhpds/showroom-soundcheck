import type {
	SessionDetail,
	SessionListItem,
	GroupDetail,
	GroupListItem,
	PaginatedResponse,
	ListParams,
	WorkshopListResponse,
	WorkshopSummary,
	WorkshopCheckStatusMap,
	WorkshopStatus
} from './types';

const BASE = '/api';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
	const resp = await fetch(url, init);
	if (!resp.ok) {
		let message: string;
		try {
			const body = await resp.json();
			const raw = body.detail || body.message || '';
			message =
				typeof raw === 'string' && raw.length > 0 && raw.length < 200
					? raw
					: `Request failed (${resp.status})`;
		} catch {
			message = `Request failed (${resp.status})`;
		}
		throw new Error(message);
	}
	return resp.json();
}

export async function listSessions(
	params: ListParams = {},
	init?: RequestInit
): Promise<PaginatedResponse<SessionListItem>> {
	const searchParams = new URLSearchParams();
	if (params.page) searchParams.set('page', String(params.page));
	if (params.per_page) searchParams.set('per_page', String(params.per_page));
	if (params.search) searchParams.set('search', params.search);
	const qs = searchParams.toString();
	return fetchJson(`${BASE}/sessions${qs ? `?${qs}` : ''}`, init);
}

export async function getSession(sessionId: string, init?: RequestInit): Promise<SessionDetail> {
	return fetchJson(`${BASE}/sessions/${sessionId}`, init);
}

export async function createSession(body: {
	urls?: string[];
	guids?: string[];
	workshop_guids?: string[];
	resource_pools?: string[];
	name?: string;
	babylon_cluster?: string;
}): Promise<{ session_id: string }> {
	return fetchJson(`${BASE}/sessions`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
}

export async function cloneSession(sessionId: string): Promise<{ session_id: string }> {
	return fetchJson(`${BASE}/sessions/${sessionId}/clone`, { method: 'POST' });
}

export async function deleteSession(sessionId: string): Promise<void> {
	await fetchJson(`${BASE}/sessions/${sessionId}`, { method: 'DELETE' });
}

export async function toggleSessionPin(sessionId: string): Promise<{ pinned: boolean }> {
	return fetchJson(`${BASE}/sessions/${sessionId}/pin`, { method: 'PATCH' });
}

export async function listGroups(
	params: ListParams = {},
	init?: RequestInit
): Promise<PaginatedResponse<GroupListItem>> {
	const searchParams = new URLSearchParams();
	if (params.page) searchParams.set('page', String(params.page));
	if (params.per_page) searchParams.set('per_page', String(params.per_page));
	if (params.search) searchParams.set('search', params.search);
	const qs = searchParams.toString();
	return fetchJson(`${BASE}/groups${qs ? `?${qs}` : ''}`, init);
}

export async function getGroup(groupId: string, init?: RequestInit): Promise<GroupDetail> {
	return fetchJson(`${BASE}/groups/${groupId}`, init);
}

export async function createGroup(body: {
	name: string;
	guids?: string[];
	workshop_guids?: string[];
	resource_pools?: string[];
	babylon_cluster?: string;
}): Promise<{ group_id: string }> {
	return fetchJson(`${BASE}/groups`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
}

export async function deleteGroup(groupId: string): Promise<void> {
	await fetchJson(`${BASE}/groups/${groupId}`, { method: 'DELETE' });
}

export async function toggleGroupPin(groupId: string): Promise<{ pinned: boolean }> {
	return fetchJson(`${BASE}/groups/${groupId}/pin`, { method: 'PATCH' });
}

export async function runGroupChecks(groupId: string): Promise<void> {
	await fetchJson(`${BASE}/groups/${groupId}/run`, { method: 'POST' });
}

export async function runGroupSource(
	groupId: string,
	sourceType: string,
	sourceValue: string
): Promise<void> {
	await fetchJson(`${BASE}/groups/${groupId}/run-source`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ source_type: sourceType, source_value: sourceValue })
	});
}

export async function renameGroup(groupId: string, name: string): Promise<void> {
	await fetchJson(`${BASE}/groups/${groupId}/name`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name })
	});
}

export async function addGroupSource(
	groupId: string,
	sourceType: string,
	sourceValue: string
): Promise<void> {
	await fetchJson(`${BASE}/groups/${groupId}/sources`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ source_type: sourceType, source_value: sourceValue })
	});
}

export async function removeGroupSource(
	groupId: string,
	sourceType: string,
	sourceValue: string
): Promise<void> {
	await fetchJson(
		`${BASE}/groups/${groupId}/sources/${encodeURIComponent(sourceType)}/${encodeURIComponent(sourceValue)}`,
		{ method: 'DELETE' }
	);
}

export async function syncGroupMetadata(groupId: string): Promise<void> {
	await fetchJson(`${BASE}/groups/${groupId}/sync-metadata`, { method: 'POST' });
}

export async function getClusters(): Promise<{ clusters: string[] }> {
	return fetchJson(`${BASE}/config/clusters`);
}

// ---------------------------------------------------------------------------
// Workshops
// ---------------------------------------------------------------------------

export interface WorkshopListParams {
	cluster?: string[];
	status?: WorkshopStatus[];
	white_glove?: 'true';
	provision_type?: 'self_service' | 'demo_team';
	has_failures?: boolean;
	from_time?: string;
	to_time?: string;
}

export async function listWorkshops(
	params: WorkshopListParams = {},
	init?: RequestInit
): Promise<WorkshopListResponse> {
	const searchParams = new URLSearchParams();
	if (params.cluster) {
		for (const c of params.cluster) searchParams.append('cluster', c);
	}
	if (params.status) {
		for (const s of params.status) searchParams.append('status', s);
	}
	if (params.white_glove) searchParams.set('white_glove', params.white_glove);
	if (params.provision_type) searchParams.set('provision_type', params.provision_type);
	if (params.has_failures) searchParams.set('has_failures', 'true');
	if (params.from_time) searchParams.set('from_time', params.from_time);
	if (params.to_time) searchParams.set('to_time', params.to_time);
	const qs = searchParams.toString();
	return fetchJson(`${BASE}/workshops${qs ? `?${qs}` : ''}`, init);
}

export async function getWorkshopsSummary(init?: RequestInit): Promise<WorkshopSummary> {
	return fetchJson(`${BASE}/workshops/summary`, init);
}

export async function getWorkshopCheckStatuses(
	workshopIds: string[]
): Promise<WorkshopCheckStatusMap> {
	const resp = await fetchJson<{ statuses: WorkshopCheckStatusMap }>(
		`${BASE}/workshops/check-status`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ workshop_ids: workshopIds })
		}
	);
	return resp.statuses;
}

export function sessionStream(sessionId: string): EventSource {
	return new EventSource(`${BASE}/sessions/${sessionId}/stream`);
}

export function groupStream(groupId: string): EventSource {
	return new EventSource(`${BASE}/groups/${groupId}/stream`);
}

export async function checkRedirect(params: URLSearchParams, init?: RequestInit): Promise<string> {
	const resp = await fetchJson<{ session_id: string }>(
		`${BASE}/check?${params.toString()}`,
		init
	);
	return resp.session_id;
}
