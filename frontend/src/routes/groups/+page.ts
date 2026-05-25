import { listGroups } from '$lib/api';

export async function load() {
	const initialData = await listGroups({
		page: 1,
		per_page: 20
	});
	return { initialData };
}
