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

export function getTimeRange(timeWindow: string): { from_time?: string; to_time?: string } {
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
	running: { bg: '#e7f5e8', text: '#1e4620', border: '#6ec071', label: 'Running', colorName: 'green' },
	provisioning: { bg: '#e7f1fa', text: '#003d73', border: '#73bcf7', label: 'Provisioning', colorName: 'blue' },
	scheduled: { bg: '#fef6e6', text: '#6b4400', border: '#f0c75e', label: 'Scheduled', colorName: 'gold' },
	stopped: { bg: '#f0f0f0', text: '#3e4045', border: '#b8bbbe', label: 'Stopped', colorName: 'grey' },
	degraded: { bg: '#fef3e8', text: '#6e3101', border: '#f4a460', label: 'Degraded', colorName: 'orange' },
	failed: { bg: '#fce8e6', text: '#7d1007', border: '#e87a72', label: 'Failed', colorName: 'red' },
	completed: { bg: '#f0f0f0', text: '#4a4a4a', border: '#d2d2d2', label: 'Completed', colorName: 'grey' },
	unknown: { bg: '#f0f0f0', text: '#4a4a4a', border: '#d2d2d2', label: 'Unknown', colorName: 'grey' }
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

export const VALID_VIEW_MODES = ['table', 'timeline'] as const;
export type ViewModeFilter = (typeof VALID_VIEW_MODES)[number];

export const ALL_WORKSHOP_STATUSES: WorkshopStatus[] = [
	'scheduled', 'provisioning', 'running', 'stopped', 'degraded', 'failed', 'completed'
];
