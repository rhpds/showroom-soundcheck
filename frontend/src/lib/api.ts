import type {
	SessionDetail,
	SessionListItem,
	GroupDetail,
	GroupListItem,
	PaginatedResponse,
	ListParams,
	CheckType
} from './types';

const BASE = '/api';

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
	const resp = await fetch(url, init);
	if (!resp.ok) {
		let message: string;
		try {
			const body = await resp.json();
			message = body.detail || body.message || `Request failed (${resp.status})`;
		} catch {
			message = `Request failed (${resp.status})`;
		}
		throw new Error(message);
	}
	return resp.json();
}

export async function listSessions(
	params: ListParams = {}
): Promise<PaginatedResponse<SessionListItem>> {
	const searchParams = new URLSearchParams();
	if (params.page) searchParams.set('page', String(params.page));
	if (params.per_page) searchParams.set('per_page', String(params.per_page));
	if (params.search) searchParams.set('search', params.search);
	const qs = searchParams.toString();
	return fetchJson(`${BASE}/sessions${qs ? `?${qs}` : ''}`);
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
	return fetchJson(`${BASE}/sessions/${sessionId}`);
}

export async function createSession(body: {
	urls?: string[];
	guids?: string[];
	workshop_guids?: string[];
	resource_pools?: string[];
	check_type?: CheckType;
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
	params: ListParams = {}
): Promise<PaginatedResponse<GroupListItem>> {
	const searchParams = new URLSearchParams();
	if (params.page) searchParams.set('page', String(params.page));
	if (params.per_page) searchParams.set('per_page', String(params.per_page));
	if (params.search) searchParams.set('search', params.search);
	const qs = searchParams.toString();
	return fetchJson(`${BASE}/groups${qs ? `?${qs}` : ''}`);
}

export async function getGroup(groupId: string): Promise<GroupDetail> {
	return fetchJson(`${BASE}/groups/${groupId}`);
}

export async function createGroup(body: {
	name: string;
	guids?: string[];
	workshop_guids?: string[];
	resource_pools?: string[];
	check_type?: CheckType;
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

export function sessionStream(sessionId: string): EventSource {
	return new EventSource(`${BASE}/sessions/${sessionId}/stream`);
}

export function groupStream(groupId: string): EventSource {
	return new EventSource(`${BASE}/groups/${groupId}/stream`);
}

export async function checkRedirect(params: URLSearchParams): Promise<string> {
	const resp = await fetchJson<{ session_id: string }>(`${BASE}/check?${params.toString()}`);
	return resp.session_id;
}
