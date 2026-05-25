import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/api': {
				target: process.env.VITE_API_TARGET || 'http://localhost:8000',
				changeOrigin: true
			}
		}
	},
	ssr: {
		noExternal: ['@patternfly/patternfly']
	}
});
