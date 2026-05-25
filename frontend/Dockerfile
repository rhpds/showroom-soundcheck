##
# Showroom Soundcheck Frontend
#
# Multi-stage build:
#   1. Build SvelteKit static output (full Node image with npm)
#   2. Serve with a zero-dependency Node.js server (minimal image)
##

# ---------------------------------------------------------------------------
# Stage 1: build SvelteKit frontend
# ---------------------------------------------------------------------------
FROM registry.access.redhat.com/ubi10/nodejs-22:latest AS build

USER 0
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY . .
RUN cp node_modules/@patternfly/patternfly/dist/patternfly.min.css static/patternfly.min.css
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Node.js runtime — static files + /api reverse proxy
# ---------------------------------------------------------------------------
FROM registry.access.redhat.com/ubi10/nodejs-22-minimal:latest

WORKDIR /app

COPY .docker/server.js .
COPY --from=build /app/build ./build

EXPOSE 5173

USER 1001

CMD ["node", "server.js"]
