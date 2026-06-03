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

export const ISSUE_STATUSES: Status[] = ['error', 'unhealthy', 'degraded'];
export const IN_PROGRESS_STATUSES: Status[] = ['running', 'pending', 'provisioning'];
export const TERMINAL_STATUSES: Status[] = ['healthy', 'degraded', 'unhealthy', 'error'];
export const STATUS_SORT_ORDER: Record<Status, number> = {
	running: 0,
	error: 1,
	degraded: 2,
	provisioning: 3,
	pending: 4,
	unhealthy: 5,
	healthy: 6,
	completed: 7,
	failed: 8
};

type ProvisionStatus =
	| 'provisioning'
	| 'ready'
	| 'destroying'
	| 'provision-failed'
	| 'unhealthy';

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

type TabInitialState = 'active' | 'deferred' | 'skip';

export interface TabDetail {
	name: string;
	url?: string;
	reachable: boolean;
	status_code?: number;
	iframe_blocked?: boolean;
	external?: boolean;
	error?: string;
	initial_state?: TabInitialState;
}

export interface ContentPageDetail {
	name: string;
	reachable: boolean;
	status_code?: number;
	url?: string;
}

type CheckDetail =
	| { legacy: true }
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
	provision_status: ProvisionStatus | null;
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
	tier: number;
	is_healthy: boolean;
	status_code: number | null;
	response_time_ms: number;
	error_message: string | null;
	detail: CheckDetail | null;
	checked_at: string;
}

interface SessionPublic {
	id: number;
	session_id: string;
	name: string;
	group_id: string | null;
	group_run_id: string | null;
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
	catalog_base_url: string;
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

// ---------------------------------------------------------------------------
// Workshop Dashboard
// ---------------------------------------------------------------------------

export type WorkshopStatus =
	| 'scheduled'
	| 'provisioning'
	| 'running'
	| 'stopped'
	| 'degraded'
	| 'failed'
	| 'completed'
	| 'unknown';

export interface WorkshopDashboardItem {
	name: string;
	namespace: string;
	display_name: string;
	cluster: string;
	catalog_item: string;
	requester: string;
	ordered_by: string;
	workshop_id: string;
	workshop_url: string;
	catalog_url: string;

	status: WorkshopStatus;

	lifespan_start: string;
	lifespan_end: string;
	ready_by: string;
	action_start: string;
	action_stop: string;

	provision_ordered: number;
	provision_active: number;
	provision_failed: number;
	provision_retries: number;

	users_assigned: number;
	users_available: number;
	users_total: number;

	white_glove: boolean;
	demo_team_provisioned: boolean;
	locked: boolean;
	disable_auto_stop: boolean;
	open_registration: boolean;
	access_password_set: boolean;
}

export interface WorkshopSummary {
	total: number;
	scheduled: number;
	provisioning: number;
	running: number;
	stopped: number;
	degraded: number;
	failed: number;
	completed: number;
}

export interface MultiWorkshopAsset {
	display_name: string;
	key: string;
	workshop_id: string;
	name: string;
	namespace: string;
}

export interface MultiWorkshopDashboardItem {
	name: string;
	namespace: string;
	display_name: string;
	cluster: string;
	multi_workshop_id: string;
	catalog_url: string;
	requester: string;
	ordered_by: string;
	purpose: string;
	number_seats: number;
	start_date: string;
	end_date: string;
	status: WorkshopStatus;
	assets: MultiWorkshopAsset[];
	children: WorkshopDashboardItem[];
	provision_ordered: number;
	provision_active: number;
	provision_failed: number;
	users_assigned: number;
	users_total: number;
}

export interface WorkshopListResponse {
	items: WorkshopDashboardItem[];
	multi_workshops: MultiWorkshopDashboardItem[];
	summary: WorkshopSummary;
	cluster_errors: string[];
	fetched_at: string;
}

// ---------------------------------------------------------------------------
// Workshop Check Status
// ---------------------------------------------------------------------------

export type CheckSessionStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface WorkshopCheckStatusEntry {
	status: CheckSessionStatus;
	session_id: string;
	created_at: string;
}

export type WorkshopCheckStatusMap = Record<string, WorkshopCheckStatusEntry | null>;

export interface ListParams {
	page?: number;
	per_page?: number;
	search?: string;
}

type StatusColor = 'blue' | 'green' | 'red' | 'gold' | 'orange';

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
