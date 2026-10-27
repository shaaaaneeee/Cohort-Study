import { vi } from "vitest";

import type { ApiClient } from "../api/client";
import type { ChatResult, Metadata, StudySpec } from "../types";

export const META: Metadata = {
  dataset: "my_study",
  exposures: [{ name: "program_a", label: "Programme A" }],
  person_attributes: ["ethnicity", "gender", "residence_status"],
  person_covariates: ["age", "ethnicity", "gender", "residence_status"],
  sources: [
    {
      name: "condition",
      label: "Chronic conditions",
      granularity: "year",
      coverage: { start: null, end: "2025-12-31" },
      dimensions: [{ name: "condition_name", label: "Condition" }],
      measures: [],
    },
    {
      name: "ed_episodes",
      label: "ED attendances",
      granularity: "day",
      coverage: { start: "2018-01-01", end: "2025-12-31" },
      dimensions: [{ name: "mode_of_arrival", label: "Mode of arrival" }],
      measures: [
        {
          name: "los_hours",
          label: "Length of stay (hours)",
          aggregations: ["mean", "sum", "max"],
        },
      ],
    },
  ],
  aggregations: [
    { name: "count", description: "Number of events" },
    { name: "binary", description: "1 if there is at least one event, otherwise 0" },
    { name: "mean", description: "Mean of a numeric measure" },
    { name: "time_to_first", description: "Days to the first event" },
  ],
  roles: ["covariate", "outcome", "inclusion"],
  window_units: ["days", "months", "years"],
  period_grains: ["month", "quarter", "year"],
};

export const DRAFT: StudySpec = {
  exposure: "program_a",
  seed: 0,
  age_min: 18,
  age_max: 80,
  person_filters: { gender: ["F"] },
  person_covariates: ["age", "gender"],
  features: [
    {
      name: "ed_after",
      label: "ED attendances, 12 months after",
      source: "ed_episodes",
      filters: {},
      window: { anchor: "index", from: 1, to: 12, unit: "months" },
      aggregation: "count",
      role: "outcome",
    },
  ],
};

export function chatResult(overrides: Partial<ChatResult> = {}): ChatResult {
  return {
    status: "ready",
    reply: "Here is the study. Review it in the builder.",
    questions: [],
    draft: DRAFT,
    issues: [],
    model: { model: "count", measure: "Rate ratio", name: "Poisson regression", reason: "Counts." },
    ...overrides,
  };
}

/** An ApiClient whose every method is a mock; override the ones a test needs. */
export function fakeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    metadata: vi.fn(() => Promise.resolve(META)),
    values: vi.fn((_source: string, dimension: string) =>
      Promise.resolve(dimension === "gender" ? ["F", "M"] : ["A", "B"]),
    ),
    check: vi.fn(() => Promise.resolve({ issues: [], model: null })),
    attrition: vi.fn(() =>
      Promise.resolve({
        steps: [{ step: "Starting population", treated: 10, control: 20 }],
        issues: [],
      }),
    ),
    preview: vi.fn(() => Promise.reject(new Error("not used"))),
    analysis: vi.fn(() => Promise.reject(new Error("not used"))),
    chat: vi.fn(() => Promise.resolve(chatResult())),
    ...overrides,
  };
}
