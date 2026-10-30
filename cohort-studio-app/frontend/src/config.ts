// Runtime configuration.
//
// Vite bakes import.meta.env into the bundle at build time, which would tie an
// image to one environment. Instead /config.js sets window.__APP_CONFIG__ when
// the page loads; the container writes that file from its environment at
// start-up (docker-entrypoint.sh), so the same image runs anywhere. The
// VITE_ variables are only a fallback for builds without /config.js.

export interface AppConfig {
  /** Base URL of the backend, without a trailing slash. */
  apiBaseUrl: string;
  /** Optional shared key sent as X-API-Key (see docs/deployment.md). */
  apiKey: string;
}

declare global {
  interface Window {
    __APP_CONFIG__?: Partial<AppConfig>;
  }
}

export function loadConfig(
  source: Partial<AppConfig> | undefined = window.__APP_CONFIG__,
): AppConfig {
  const env = import.meta.env as Record<string, string | undefined>;
  const apiBaseUrl = source?.apiBaseUrl ?? env.VITE_API_BASE_URL ?? "";
  return {
    apiBaseUrl: apiBaseUrl.replace(/\/+$/, ""),
    apiKey: source?.apiKey ?? env.VITE_API_KEY ?? "",
  };
}

export const config: AppConfig = loadConfig();
