#!/bin/sh
# Write the runtime config the page loads before the app (see src/config.ts),
# then start the server. Values are JSON-encoded by node, so any characters
# in them are safe.
#
#   API_BASE_URL  the backend's public URL, e.g. https://api.example.org
#   API_KEY       optional shared key sent as X-API-Key (visible to anyone who
#                 loads the page; see docs/deployment.md)
set -eu

node -e '
const config = {
  apiBaseUrl: process.env.API_BASE_URL || "",
  apiKey: process.env.API_KEY || "",
};
process.stdout.write("window.__APP_CONFIG__ = " + JSON.stringify(config) + ";\n");
' > dist/config.js

exec "$@"
