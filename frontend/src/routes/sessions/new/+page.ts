import type { PageLoad } from './$types';
import { getClusters } from '$lib/api';

export const load: PageLoad = async () => {
	const { clusters } = await getClusters().catch(() => ({ clusters: [] as string[] }));
	return { clusters };
};
