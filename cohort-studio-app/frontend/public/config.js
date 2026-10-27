// Runtime settings for local development (npm run dev). In the container
// this file is replaced at start-up from environment variables, so one image
// works in every environment. See docker-entrypoint.sh.
window.__APP_CONFIG__ = { apiBaseUrl: "http://localhost:8000", apiKey: "" };
