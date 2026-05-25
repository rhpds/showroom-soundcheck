import type { PageLoad } from './$types';
import { listSessions } from '$lib/api';

export const load: PageLoad = async ({ url }) => {
	const page = parseInt(url.searchParams.get('page') ?? '1');
	const per_page = parseInt(url.searchParams.get('per_page') ?? '20');
	const search = url.searchParams.get('search') ?? '';
	const sessions = await listSessions({
		page,
		per_page,
		search: search || undefined
	});
	return { sessions, initialPage: page, initialPerPage: per_page, initialSearch: search };
};
