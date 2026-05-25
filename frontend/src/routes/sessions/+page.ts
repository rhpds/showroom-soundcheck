import { listSessions } from '$lib/api';

export async function load() {
	const initialData = await listSessions({
		page: 1,
		per_page: 20
	});
	return { initialData };
}
