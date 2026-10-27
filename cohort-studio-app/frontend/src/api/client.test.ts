import { describe, expect, it, vi } from "vitest";

import { loadConfig } from "../config";
import { ApiError, createApiClient } from "./client";

function respond(status: number, body: unknown) {
  return vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

describe("the API client", () => {
  it("calls the configured backend with the study as JSON", async () => {
    const fetchImpl = respond(200, { issues: [], model: null });
    const client = createApiClient("https://api.example.org", "", fetchImpl);
    await client.check({
      exposure: "program_a",
      seed: 0,
      person_filters: {},
      person_covariates: [],
      features: [],
    });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.org/api/study/check");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toMatchObject({ exposure: "program_a" });
  });

  it("sends the API key when one is configured", async () => {
    const fetchImpl = respond(200, []);
    await createApiClient("", "k3y", fetchImpl).values("person", "gender");
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/values/person/gender");
    expect((init.headers as Record<string, string>)["X-API-Key"]).toBe("k3y");
  });

  it("turns error responses into ApiErrors with the backend's issues", async () => {
    const issues = [
      { level: "error", code: "covariate_lookahead", message: "Too late.", feature: "x" },
    ];
    const client = createApiClient(
      "",
      "",
      respond(422, { message: "The study has design errors.", issues }),
    );
    const error = await client.metadata().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).issues).toEqual(issues);
  });

  it("reports a network failure plainly", async () => {
    const client = createApiClient(
      "",
      "",
      vi.fn(() => Promise.reject(new TypeError("fetch failed"))),
    );
    await expect(client.metadata()).rejects.toThrow("Could not reach the server");
  });
});

describe("runtime config", () => {
  it("comes from window.__APP_CONFIG__ and drops a trailing slash", () => {
    expect(loadConfig({ apiBaseUrl: "https://api.example.org/", apiKey: "k" })).toEqual({
      apiBaseUrl: "https://api.example.org",
      apiKey: "k",
    });
  });
});
