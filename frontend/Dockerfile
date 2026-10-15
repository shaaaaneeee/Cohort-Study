FROM nginx:1.27-alpine

COPY index.html /usr/share/nginx/html/index.html

# The nginx image runs scripts in /docker-entrypoint.d/ before starting.
# This one writes config.js from the BACKEND_URL environment variable, so the
# same image works in any environment.
COPY write-config.sh /docker-entrypoint.d/40-write-config.sh
RUN chmod +x /docker-entrypoint.d/40-write-config.sh

EXPOSE 80
