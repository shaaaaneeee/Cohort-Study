#!/bin/sh
# Writes the backend's public URL into config.js at container start.
set -e
cat > /usr/share/nginx/html/config.js <<EOF
window.CONFIG = { BACKEND_URL: "${BACKEND_URL:-}" };
EOF
echo "config.js written with BACKEND_URL=${BACKEND_URL:-<not set>}"
