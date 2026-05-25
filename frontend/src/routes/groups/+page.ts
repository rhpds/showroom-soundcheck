import type { PageLoad } from './$types';
import { listGroups } from '$lib/api';

export const load: PageLoad = async ({ url }) => {
	const page = parseInt(url.searchParams.get('page') ?? '1');
	const per_page = parseInt(url.searchParams.get('per_page') ?? '20');
	const search = url.searchParams.get('search') ?? '';
	const groups = await listGroups({
		page,
		per_page,
		search: search || undefined
	});
	return { groups, initialPage: page, initialPerPage: per_page, initialSearch: search };
};
