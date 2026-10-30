# syntax=docker/dockerfile:1
#
# Cohort Studio web app: built with Vite, served as static files by `serve`
# from the same node:26.12.1 image. The API URL is not baked in: the
# entrypoint writes /config.js from the environment when the container starts.

# ---------------------------------------------------------------- build
FROM node:26.12.1 AS build
WORKDIR /app

# Dependencies first, so code changes reuse this layer.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# -------------------------------------------------------------- runtime
FROM node:26.12.1 AS runtime
ENV NODE_ENV=production \
    PORT=8080
WORKDIR /app

# Only the static server is needed at run time, at the version package.json pins.
RUN npm install --global --no-audit --no-fund serve@14.2.6 && npm cache clean --force

COPY --from=build --chown=node:node /app/dist ./dist
COPY --chown=node:node docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod 0755 ./docker-entrypoint.sh

# The image's built-in non-root user. It owns dist/ so the entrypoint can
# write config.js there.
USER node
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:' + (process.env.PORT || 8080) + '/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["sh", "-c", "exec serve --single --no-clipboard --listen tcp://0.0.0.0:${PORT} dist"]
