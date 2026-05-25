##
# Showroom Soundcheck Frontend
#
# Multi-stage build:
#   1. Build SvelteKit static output
#   2. Serve with nginx (reverse-proxies /api to backend)
##

# ---------------------------------------------------------------------------
# Stage 1: build SvelteKit frontend
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY . .
RUN cp node_modules/@patternfly/patternfly/dist/patternfly.min.css static/patternfly.min.css
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: nginx runtime
# ---------------------------------------------------------------------------
FROM nginx:1-alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY .docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 5173
