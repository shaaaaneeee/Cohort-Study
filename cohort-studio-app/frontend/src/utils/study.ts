// Study helpers shared by the builder, the chat and the results, ported from
// the POC's app.js so wording and defaults stay the same.
import type {
  Aggregation,
  FeatureSpec,
  Metadata,
  Role,
  SourceInfo,
  StudySpec,
  Window,
  WindowUnit,
} from "../types";

// Columns the analysis table always has; a feature cannot take these names.
export const RESERVED = ["patient_id", "index_date", "exposure", "age", "person_years"];
export const MEASURE_AGGREGATIONS: Aggregation[] = ["sum", "mean", "max"];
export const AGGREGATION_LABELS: Record<Aggregation, string> = {
  count: "Number of events",
  distinct_count: "Number of days with an event",
  binary: "Any event (yes or no)",
  sum: "Total of a measure",
  mean: "Average of a measure",
  max: "Largest value of a measure",
  rate: "Events per year",
  time_to_first: "Time to first event",
};
export const OPERATORS: [NonNullable<FeatureSpec["keep_if"]>["op"], string][] = [
  ["==", "equal to"],
  ["!=", "not equal to"],
  [">=", "at least"],
  [">", "more than"],
  ["<=", "at most"],
  ["<", "less than"],
];
export const ROLE_NAMES: Record<Role, string> = {
  inclusion: "inclusion criterion",
  covariate: "covariate",
  outcome: "outcome",
};

export function emptyStudy(meta: Metadata | null): StudySpec {
  return {
    exposure: meta?.exposures[0]?.name ?? "",
    seed: 0,
    age_min: null,
    age_max: null,
    person_filters: {},
    person_covariates: ["age"],
    features: [],
  };
}

/** Fill in every default, so the store always holds a complete StudySpec. */
export function normaliseStudy(study: Partial<StudySpec>, meta: Metadata | null): StudySpec {
  const base = emptyStudy(meta);
  return {
    ...base,
    ...study,
    age_min: study.age_min ?? null,
    age_max: study.age_max ?? null,
    person_filters: { ...(study.person_filters ?? {}) },
    person_covariates: [...(study.person_covariates ?? base.person_covariates)],
    features: (study.features ?? []).map((f) => ({
      ...f,
      filters: { ...f.filters },
      window: { ...f.window, anchor: "index" },
    })),
  };
}

/** True for a study nobody has touched yet: nothing to refine. */
export function isBlankStudy(study: StudySpec, meta: Metadata | null): boolean {
  return JSON.stringify(study) === JSON.stringify(emptyStudy(meta));
}

export function readable(name: string): string {
  const text = name.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function sourceOf(meta: Metadata | null, name: string): SourceInfo | null {
  return meta?.sources.find((s) => s.name === name) ?? null;
}

export function windowText(w: Window, source: SourceInfo | null): string {
  const anchor = source?.granularity === "year" ? "the index year" : "the index date";
  if (w.to <= -1) return `${-w.to} to ${-w.from} ${w.unit} before ${anchor}`;
  if (w.from >= 1) return `${w.from} to ${w.to} ${w.unit} after ${anchor}`;
  return `${w.from} to ${w.to} ${w.unit} around ${anchor}`;
}

/** One line saying what a feature counts, in words. */
export function describe(f: FeatureSpec, meta: Metadata | null): string {
  const source = sourceOf(meta, f.source);
  const parts = [source ? source.label : f.source];
  for (const [dimension, values] of Object.entries(f.filters)) {
    const found = source?.dimensions.find((d) => d.name === dimension);
    parts.push(`${found ? found.label : dimension}: ${values.join(", ")}`);
  }
  if (MEASURE_AGGREGATIONS.includes(f.aggregation)) {
    const measure = source?.measures.find((m) => m.name === f.measure);
    parts.push(`${f.aggregation} of ${measure ? measure.label : (f.measure ?? "")}`);
  } else {
    parts.push(AGGREGATION_LABELS[f.aggregation].toLowerCase());
  }
  parts.push(windowText(f.window, source));
  if (f.periodise) parts.push(`in ${f.periodise.n} periods of a ${f.periodise.grain}`);
  if (f.keep_if) {
    const keep = f.keep_if;
    const op = OPERATORS.find(([code]) => code === keep.op);
    parts.push(`keep if ${op ? op[1] : keep.op} ${keep.value}`);
  }
  return parts.join(" · ");
}

export function unitsFor(source: SourceInfo, meta: Metadata): WindowUnit[] {
  // Windows cannot be finer than what the source records.
  if (source.granularity === "year") return ["years"];
  if (source.granularity === "month") return ["months", "years"];
  return meta.window_units as WindowUnit[];
}

export type Preset = [label: string, from: number, to: number, unit: WindowUnit];

export function presetsFor(role: Role, source: SourceInfo, meta: Metadata): Preset[] {
  const before = role !== "outcome";
  let presets: Preset[];
  if (source.granularity === "year") {
    presets = before
      ? [
          ["Any year before the index year", -50, -1, "years"],
          ["The year before the index year", -1, -1, "years"],
        ]
      : [
          ["The year after the index year", 1, 1, "years"],
          ["Two years after", 1, 2, "years"],
        ];
  } else {
    presets = before
      ? [
          ["12 months before", -12, -1, "months"],
          ["30 days before", -30, -1, "days"],
          ["2 years before", -24, -1, "months"],
        ]
      : [
          ["12 months after", 1, 12, "months"],
          ["30 days after", 1, 30, "days"],
          ["2 years after", 1, 24, "months"],
        ];
  }
  const units = unitsFor(source, meta);
  return presets.filter((p) => units.includes(p[3]));
}

export function aggregationsFor(role: Role, source: SourceInfo, meta: Metadata): Aggregation[] {
  const allowed: Aggregation[] = [];
  for (const a of meta.aggregations) {
    const name = a.name as Aggregation;
    const needsMeasure = MEASURE_AGGREGATIONS.includes(name);
    if (needsMeasure && !source.measures.some((m) => m.aggregations.includes(name))) continue;
    // No model is defined for a summed or averaged measure as the outcome.
    if (needsMeasure && role === "outcome") continue;
    // Time to event needs exact dates and is only ever an outcome.
    if (name === "time_to_first" && (role !== "outcome" || source.granularity !== "day")) continue;
    allowed.push(name);
  }
  return allowed;
}

export function defaultFeature(role: Role, meta: Metadata): FeatureSpec {
  // Inclusion criteria usually test a condition; covariates and outcomes
  // usually count events. Pick a source to match.
  const sources = meta.sources;
  const first = sources[0];
  if (!first) throw new Error("The dataset has no sources.");
  const source =
    role === "inclusion"
      ? (sources.find((s) => s.name === "condition") ?? first)
      : (sources.find((s) => s.granularity !== "year") ?? first);
  const preset = presetsFor(role, source, meta)[0];
  const [, from, to, unit] = preset ?? ["", -12, -1, unitsFor(source, meta)[0] ?? "years"];
  const feature: FeatureSpec = {
    name: "",
    label: "",
    source: source.name,
    filters: {},
    window: { anchor: "index", from, to, unit },
    aggregation: source.granularity === "year" ? "binary" : "count",
    role,
  };
  if (role === "inclusion") {
    feature.aggregation = "binary";
    feature.keep_if = { op: "==", value: 1 };
  }
  return feature;
}

/** A column name made from the label, so nobody has to type one. */
export function nameFor(
  label: string,
  study: StudySpec,
  meta: Metadata,
  editingIndex: number | null,
): string {
  let base = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 50)
    .replace(/_+$/, "");
  if (!/^[a-z]/.test(base)) base = `f_${base}`.replace(/_+$/, "");
  const taken = new Set([...RESERVED, ...meta.person_attributes]);
  study.features.forEach((f, index) => {
    if (index !== editingIndex) taken.add(f.name);
  });
  let name = base;
  let k = 2;
  while (taken.has(name)) {
    name = `${base}_${k}`;
    k += 1;
  }
  return name;
}

export type DraftCheck = { ok: true; study: StudySpec } | { ok: false; problems: string[] };

/**
 * Check a study the assistant proposed before it replaces the one in the
 * builder. The server has already validated it in full; this guards the
 * store against anything malformed and against names the builder does not
 * offer, so the controls can always show what the store holds.
 */
export function checkDraft(draft: unknown, meta: Metadata | null): DraftCheck {
  const problems: string[] = [];
  if (typeof draft !== "object" || draft === null) return { ok: false, problems: ["No study."] };
  const d = draft as Partial<StudySpec>;
  if (typeof d.exposure !== "string" || !d.exposure) problems.push("The study has no exposure.");
  if (meta && d.exposure && !meta.exposures.some((x) => x.name === d.exposure)) {
    problems.push(`Unknown exposure '${d.exposure}'.`);
  }
  const age = (v: unknown) => v === undefined || v === null || Number.isInteger(v);
  if (!age(d.age_min) || !age(d.age_max)) problems.push("Ages must be whole numbers.");
  if (d.features !== undefined && !Array.isArray(d.features))
    problems.push("Features must be a list.");
  for (const raw of (d.features ?? []) as unknown[]) {
    const f = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
    const label = typeof f.label === "string" ? f.label : "a feature";
    if (typeof f.name !== "string" || typeof f.label !== "string" || !f.window) {
      problems.push("A feature is incomplete.");
      continue;
    }
    if (meta && !meta.sources.some((s) => s.name === f.source)) {
      problems.push(`Unknown source '${String(f.source)}' in ${label}.`);
    }
    if (!["covariate", "outcome", "inclusion"].includes(String(f.role))) {
      problems.push(`Unknown role in ${label}.`);
    }
  }
  if (d.person_filters && meta) {
    for (const attribute of Object.keys(d.person_filters)) {
      if (!meta.person_attributes.includes(attribute)) {
        problems.push(`Unknown person attribute '${attribute}'.`);
      }
    }
  }
  if (problems.length) return { ok: false, problems };
  return { ok: true, study: normaliseStudy(d, meta) };
}
