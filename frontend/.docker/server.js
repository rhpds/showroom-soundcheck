import { createServer, request as httpRequest } from 'node:http';
import { readFile } from 'node:fs/promises';
import { join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const STATIC_DIR = join(__dirname, 'build');
const PORT = parseInt(process.env.PORT || '5173', 10);
const BACKEND_URL = new URL(process.env.BACKEND_URL || 'http://localhost:8000');

const MIME_TYPES = {
	'.html': 'text/html; charset=utf-8',
	'.js': 'application/javascript',
	'.css': 'text/css',
	'.json': 'application/json',
	'.png': 'image/png',
	'.jpg': 'image/jpeg',
	'.svg': 'image/svg+xml',
	'.ico': 'image/x-icon',
	'.woff': 'font/woff',
	'.woff2': 'font/woff2',
	'.ttf': 'font/ttf',
	'.webp': 'image/webp',
	'.webmanifest': 'application/manifest+json'
};

async function serveFile(res, filePath) {
	try {
		const data = await readFile(filePath);
		const mime = MIME_TYPES[extname(filePath)] || 'application/octet-stream';
		res.writeHead(200, { 'Content-Type': mime, 'Content-Length': data.length });
		res.end(data);
		return true;
	} catch {
		return false;
	}
}

function proxyToBackend(req, res) {
	const opts = {
		hostname: BACKEND_URL.hostname,
		port: BACKEND_URL.port || 80,
		path: req.url,
		method: req.method,
		headers: { ...req.headers, host: BACKEND_URL.host }
	};

	const proxy = httpRequest(opts, (upstream) => {
		res.writeHead(upstream.statusCode, upstream.headers);
		upstream.pipe(res);
	});

	proxy.on('error', () => {
		if (!res.headersSent) {
			res.writeHead(502, { 'Content-Type': 'text/plain' });
			res.end('Bad Gateway');
		}
	});

	req.pipe(proxy);
}

const server = createServer(async (req, res) => {
	const pathname = new URL(req.url, `http://localhost:${PORT}`).pathname;

	if (pathname.startsWith('/api/') || pathname === '/docs' || pathname === '/redoc' || pathname === '/openapi.json') {
		return proxyToBackend(req, res);
	}

	const filePath = join(STATIC_DIR, pathname === '/' ? 'index.html' : pathname);
	if (await serveFile(res, filePath)) return;

	// SPA fallback
	if (!await serveFile(res, join(STATIC_DIR, 'index.html'))) {
		res.writeHead(404, { 'Content-Type': 'text/plain' });
		res.end('Not Found');
	}
});

server.listen(PORT, '0.0.0.0', () => {
	console.log(`Frontend listening on :${PORT}`);
});
