export function relativeTime(dateStr: string): string {
	const diff = Date.now() - new Date(dateStr).getTime();
	const mins = Math.floor(diff / 60000);
	if (mins < 1) return 'just now';
	if (mins < 60) return `${mins}m ago`;
	const hours = Math.floor(mins / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	return `${days}d ago`;
}

export function getTimeRange(timeWindow: TimeWindowFilter): { from_time?: string; to_time?: string } {
	const now = new Date();
	switch (timeWindow) {
		case 'today': {
			const start = new Date(now);
			start.setHours(0, 0, 0, 0);
			const end = new Date(now);
			end.setHours(23, 59, 59, 999);
			return { from_time: start.toISOString(), to_time: end.toISOString() };
		}
		case '24h': {
			const end = new Date(now.getTime() + 24 * 60 * 60 * 1000);
			return { from_time: now.toISOString(), to_time: end.toISOString() };
		}
		case 'week': {
			const end = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
			return { from_time: now.toISOString(), to_time: end.toISOString() };
		}
		default:
			return {};
	}
}

import type { WorkshopStatus } from './types';

export interface WorkshopStatusStyle {
	bg: string;
	text: string;
	border: string;
	label: string;
	colorName: string;
}

const WORKSHOP_STATUS_MAP: Record<WorkshopStatus, WorkshopStatusStyle> = {
	running: { bg: 'var(--sc-green-bg)', text: 'var(--sc-green-text)', border: 'var(--sc-green-border)', label: 'Running', colorName: 'green' },
	provisioning: { bg: 'var(--sc-blue-bg)', text: 'var(--sc-blue-text)', border: 'var(--sc-blue-border)', label: 'Provisioning', colorName: 'blue' },
	scheduled: { bg: 'var(--sc-gold-bg)', text: 'var(--sc-gold-text)', border: 'var(--sc-gold-border)', label: 'Scheduled', colorName: 'gold' },
	stopped: { bg: 'var(--sc-muted-bg)', text: 'var(--sc-muted-text)', border: 'var(--sc-muted-border)', label: 'Stopped', colorName: 'grey' },
	degraded: { bg: 'var(--sc-orange-bg)', text: 'var(--sc-orange-text)', border: 'var(--sc-orange-border)', label: 'Degraded', colorName: 'orange' },
	failed: { bg: 'var(--sc-red-bg)', text: 'var(--sc-red-text)', border: 'var(--sc-red-border)', label: 'Failed', colorName: 'red' },
	completed: { bg: 'var(--sc-grey-bg)', text: 'var(--sc-grey-text)', border: 'var(--sc-grey-border)', label: 'Completed', colorName: 'grey' },
	unknown: { bg: 'var(--sc-grey-bg)', text: 'var(--sc-grey-text)', border: 'var(--sc-grey-border)', label: 'Unknown', colorName: 'grey' }
};

export function workshopStatusStyle(status: WorkshopStatus): WorkshopStatusStyle {
	return WORKSHOP_STATUS_MAP[status] ?? WORKSHOP_STATUS_MAP.unknown;
}

export function workshopStatusColor(status: WorkshopStatus): string {
	return workshopStatusStyle(status).colorName;
}

export function workshopStatusLabel(status: WorkshopStatus): string {
	return workshopStatusStyle(status).label;
}

export function workshopStatusBg(status: WorkshopStatus): string {
	return workshopStatusStyle(status).bg;
}

export function workshopStatusTextColor(status: WorkshopStatus): string {
	return workshopStatusStyle(status).text;
}

export function workshopStatusBorder(status: WorkshopStatus): string {
	return workshopStatusStyle(status).border;
}

export const VALID_PROVISION_TYPES = ['all', 'self_service', 'demo_team'] as const;
export type ProvisionTypeFilter = (typeof VALID_PROVISION_TYPES)[number];

export const VALID_TIME_WINDOWS = ['all', 'today', '24h', 'week'] as const;
export type TimeWindowFilter = (typeof VALID_TIME_WINDOWS)[number];

export const ENVIRONMENT_VALUES = ['prod', 'dev', 'test', 'event'] as const;
export type EnvironmentType = (typeof ENVIRONMENT_VALUES)[number];
export const VALID_ENVIRONMENT_FILTERS = ['all', ...ENVIRONMENT_VALUES] as const;
export type EnvironmentFilter = (typeof VALID_ENVIRONMENT_FILTERS)[number];

const ENVIRONMENT_LABELS: Record<EnvironmentType, string> = {
	prod: 'Prod',
	dev: 'Dev',
	test: 'Test',
	event: 'Event'
};

export function environmentLabel(env: EnvironmentType): string {
	return ENVIRONMENT_LABELS[env];
}

/**
 * Extract environment from a workshop name.
 * Names follow the pattern: `namespace.catalog-item.{env}-{random}`,
 * e.g. "openshift-cnv.ocp-virt-roadshow-2026.dev-z66th" -> "dev"
 */
export function extractEnvironment(name: string): EnvironmentType | null {
	const lastSegment = name.split('.').pop() ?? '';
	for (const env of ENVIRONMENT_VALUES) {
		if (lastSegment.startsWith(`${env}-`) || lastSegment === env) {
			return env;
		}
	}
	return null;
}

export const ALL_WORKSHOP_STATUSES: WorkshopStatus[] = [
	'scheduled', 'provisioning', 'running', 'stopped', 'degraded', 'failed', 'completed'
];
