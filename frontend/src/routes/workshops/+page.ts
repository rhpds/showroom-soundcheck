import type { PageLoad } from './$types';
import { getClusters, listWorkshops } from '$lib/api';
import type { WorkshopListResponse, WorkshopStatus } from '$lib/types';
import {
	VALID_PROVISION_TYPES,
	VALID_TIME_WINDOWS,
	ALL_WORKSHOP_STATUSES,
	getTimeRange,
	type ProvisionTypeFilter,
	type TimeWindowFilter
} from '$lib/utils';

export const load: PageLoad = async ({ url }) => {
	const hasAnyParams = url.searchParams.toString().length > 0;

	const selectedClusters = url.searchParams.getAll('cluster');
	const whiteGlove = url.searchParams.get('white_glove') === 'true';
	const multiAssetOnly = url.searchParams.get('multi_asset') === 'true';

	const rawProvType = url.searchParams.get('provision_type') || 'all';
	const provisionType: ProvisionTypeFilter = VALID_PROVISION_TYPES.includes(
		rawProvType as ProvisionTypeFilter
	)
		? (rawProvType as ProvisionTypeFilter)
		: 'all';

	const rawStatuses = url.searchParams.getAll('status');
	const selectedStatuses = rawStatuses.length > 0
		? rawStatuses.filter((s): s is WorkshopStatus =>
			ALL_WORKSHOP_STATUSES.includes(s as WorkshopStatus)
		)
		: hasAnyParams
			? []
			: (['scheduled', 'provisioning'] as WorkshopStatus[]);

	const hasFailures = url.searchParams.get('has_failures') === 'true';

	const rawTime = url.searchParams.get('time') || (hasAnyParams ? 'all' : '24h');
	const timeWindow: TimeWindowFilter = VALID_TIME_WINDOWS.includes(rawTime as TimeWindowFilter)
		? (rawTime as TimeWindowFilter)
		: '24h';

	const timeRange = getTimeRange(timeWindow);
	const workshopParams = {
		cluster: selectedClusters.length > 0 ? selectedClusters : undefined,
		status: selectedStatuses.length > 0 ? selectedStatuses : undefined,
		white_glove: whiteGlove ? ('true' as const) : undefined,
		provision_type:
			provisionType !== 'all' ? (provisionType as 'self_service' | 'demo_team') : undefined,
		has_failures: hasFailures || undefined,
		limit: 500,
		...timeRange
	};

	const [clustersResp, workshopsResult] = await Promise.all([
		getClusters(),
		listWorkshops(workshopParams).catch((): WorkshopListResponse | null => null)
	]);

	return {
		clusters: clustersResp.clusters,
		initialWorkshops: workshopsResult,
		filters: {
			selectedClusters,
			whiteGlove,
			multiAssetOnly,
			provisionType,
			selectedStatuses,
			hasFailures,
			timeWindow
		}
	};
};
