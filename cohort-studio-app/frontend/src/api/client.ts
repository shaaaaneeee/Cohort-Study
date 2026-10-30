// The one place the app talks to the backend. Every call is typed with the
// backend's own schema, and every failure becomes an ApiError carrying the
// backend's issues, so the UI shows any error the same way.
import { config } from "../config";
import type {
  AnalysisResult,
  AttritionResult,
  ChatRequest,
  ChatResult,
  CheckResult,
  FeatureSpec,
  Issue,
  Metadata,
  PreviewResult,
  StudySpec,
} from "../types";

export class ApiError extends Error {
  readonly status: number;
  readonly issues: Issue[];

  constructor(message: string, status: number, issues: Issue[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.issues = issues;
  }
}

type Fetch = typeof fetch;

export interface ApiClient {
  metadata: () => Promise<Metadata>;
  values: (source: string, dimension: string) => Promise<string[]>;
  check: (study: StudySpec) => Promise<CheckResult>;
  attrition: (study: StudySpec) => Promise<AttritionResult>;
  preview: (feature: FeatureSpec, study: StudySpec) => Promise<PreviewResult>;
  analysis: (study: StudySpec) => Promise<AnalysisResult>;
  chat: (request: ChatRequest) => Promise<ChatResult>;
}

function isErrorBody(data: unknown): data is { message: string; issues?: Issue[] } {
  return typeof data === "object" && data !== null && "message" in data;
}

export function createApiClient(
  baseUrl: string = config.apiBaseUrl,
  apiKey: string = config.apiKey,
  fetchImpl: Fetch = (...args) => fetch(...args),
): ApiClient {
  async function request<T>(path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (apiKey) headers["X-API-Key"] = apiKey;
    const init: RequestInit = { headers };
    if (body !== undefined) {
      init.method = "POST";
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let response: Response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, init);
    } catch {
      throw new ApiError("Could not reach the server. Check your connection.", 0);
    }
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      // Not JSON: the status line says what happened.
    }
    if (!response.ok) {
      const message = isErrorBody(data)
        ? data.message
        : `${response.status} ${response.statusText}`.trim();
      throw new ApiError(message, response.status, isErrorBody(data) ? (data.issues ?? []) : []);
    }
    return data as T;
  }

  const enc = encodeURIComponent;
  return {
    metadata: () => request<Metadata>("/api/metadata"),
    values: (source, dimension) =>
      request<string[]>(`/api/values/${enc(source)}/${enc(dimension)}`),
    check: (study) => request<CheckResult>("/api/study/check", study),
    attrition: (study) => request<AttritionResult>("/api/attrition", study),
    preview: (feature, study) => request<PreviewResult>("/api/preview", { feature, study }),
    analysis: (study) => request<AnalysisResult>("/api/analysis", study),
    chat: (body) => request<ChatResult>("/api/chat", body),
  };
}

export const api: ApiClient = createApiClient();
