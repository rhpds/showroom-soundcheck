export type Status =
	| 'healthy'
	| 'completed'
	| 'degraded'
	| 'error'
	| 'unhealthy'
	| 'failed'
	| 'running'
	| 'pending'
	| 'provisioning';

export type CheckType = 'readyz' | 'healthz';

export interface SessionListItem {
	id: number;
	session_id: string;
	name: string;
	group_id: string | null;
	display_label: string;
	status: Status;
	pinned: boolean;
	created_at: string;
	completed_at: string | null;
	resource_display_name: string;
	source_id: string;
}

export interface TabDetail {
	name: string;
	url?: string;
	reachable: boolean;
	status_code?: number;
	iframe_blocked?: boolean;
	external?: boolean;
	error?: string;
}

export interface ContentPageDetail {
	name: string;
	reachable: boolean;
	status_code?: number;
	url?: string;
}

export type CheckDetail =
	| { legacy: true; [key: string]: unknown }
	| { legacy?: false; tabs?: TabDetail[]; content_pages?: ContentPageDetail[] };

export interface TargetPublic {
	id: number;
	session_id: string;
	url: string;
	label: string;
	guid: string | null;
	workshop_guid: string | null;
	resource_pool_name: string | null;
	resource_name: string;
	resource_namespace: string;
	provision_status: string | null;
	status: Status;
	tier_used: number | null;
	response_time_ms: number | null;
	error_message: string | null;
	check_started_at: string | null;
	check_completed_at: string | null;
}

export interface CheckResultPublic {
	id: number;
	target_id: number;
	check_type: string;
	tier: number;
	is_healthy: boolean;
	status_code: number | null;
	response_time_ms: number;
	error_message: string | null;
	detail: CheckDetail | null;
	checked_at: string;
}

export interface SessionPublic {
	id: number;
	session_id: string;
	name: string;
	group_id: string | null;
	group_run_id: string | null;
	check_type: CheckType;
	source_urls: string[];
	source_guids: string[];
	source_workshop_guids: string[];
	source_resource_pools: string[];
	babylon_cluster: string;
	display_label: string;
	status: Status;
	pinned: boolean;
	created_at: string;
	completed_at: string | null;
	resource_name: string;
	resource_namespace: string;
	resource_kind: string;
	resource_display_name: string;
	resource_metadata: Record<string, unknown>;
}

export interface SessionDetail {
	session: SessionPublic;
	targets: TargetPublic[];
	results: CheckResultPublic[];
}

export interface GroupListItem {
	id: number;
	group_id: string;
	name: string;
	status: Status;
	pinned: boolean;
	created_at: string;
	source_count: number;
}

export interface GroupPublic {
	id: number;
	group_id: string;
	name: string;
	check_type: CheckType;
	babylon_cluster: string;
	source_guids: string[];
	source_workshop_guids: string[];
	source_resource_pools: string[];
	source_metadata: Record<string, Record<string, unknown>>;
	status: Status;
	pinned: boolean;
	created_at: string;
}

export interface GroupRunPublic {
	id: number;
	run_id: string;
	group_id: string;
	status: Status;
	created_at: string;
	completed_at: string | null;
}

export interface GroupDetail {
	group: GroupPublic;
	runs: GroupRunPublic[];
	run_sessions: Record<string, SessionListItem[]>;
	targets_by_session: Record<string, TargetPublic[]>;
}

export interface PaginatedResponse<T> {
	items: T[];
	total: number;
	page: number;
	per_page: number;
}

export interface ListParams {
	page?: number;
	per_page?: number;
	search?: string;
}

export type StatusColor = 'blue' | 'green' | 'red' | 'gold' | 'orange' | 'purple' | 'grey';

export function statusColor(status: Status): StatusColor {
	switch (status) {
		case 'healthy':
		case 'completed':
			return 'green';
		case 'degraded':
			return 'gold';
		case 'error':
		case 'unhealthy':
		case 'failed':
			return 'red';
		case 'running':
			return 'blue';
		case 'pending':
			return 'gold';
		case 'provisioning':
			return 'orange';
	}
}
