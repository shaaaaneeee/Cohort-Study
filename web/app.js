// The study builder. Holds the study being edited, talks to the API and
// draws steps 1 and 2. results.js draws step 3.
//
// The study object has exactly the shape of StudySpec in features.py, so it
// can be sent to the API, saved to a file and opened again unchanged.
import { el, formatCount, formatNumber, issueItems, numberTable, readable } from "./dom.js";
import { renderResults, renderResultsError, setResultsBusy } from "./results.js";

const STORAGE_KEY = "cohort-studio:study";
// Columns the analysis table always has; a feature cannot take these names.
const RESERVED = ["patient_id", "index_date", "exposure", "age", "person_years"];
const MEASURE_AGGREGATIONS = ["sum", "mean", "max"];
const AGGREGATION_LABELS = {
  count: "Number of events",
  distinct_count: "Number of days with an event",
  binary: "Any event (yes or no)",
  sum: "Total of a measure",
  mean: "Average of a measure",
  max: "Largest value of a measure",
  rate: "Events per year",
  time_to_first: "Time to first event",
};
const OPERATORS = [
  ["==", "equal to"], ["!=", "not equal to"], [">=", "at least"],
  [">", "more than"], ["<=", "at most"], ["<", "less than"],
];
const ROLE_NAMES = { inclusion: "inclusion criterion", covariate: "covariate", outcome: "outcome" };

const state = {
  meta: null,         // what the builder can offer, from /api/metadata
  study: null,        // the study being edited
  values: new Map(),  // "source/dimension" -> promise of its values
  issues: [],         // the latest design check
  editing: null,      // {role, index} while the feature dialog is open
};

const $ = (id) => document.getElementById(id);


// ----------------------------------------------------------------- server

async function api(path, body) {
  const options = {};
  if (body !== undefined) {
    options.method = "POST";
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const error = new Error((data && data.message) || `${response.status} ${response.statusText}`);
    error.issues = (data && data.issues) || [];
    throw error;
  }
  return data;
}

function valuesOf(source, dimension) {
  // Fetched once per page load. A failed request is forgotten so the next
  // attempt tries again.
  const key = `${source}/${dimension}`;
  if (!state.values.has(key)) {
    const request = api(`/api/values/${encodeURIComponent(source)}/${encodeURIComponent(dimension)}`)
      .catch((error) => {
        state.values.delete(key);
        throw error;
      });
    state.values.set(key, request);
  }
  return state.values.get(key);
}


// ------------------------------------------------------------- the study

function newStudy() {
  return {
    exposure: state.meta.exposures[0].name,
    seed: 0,
    age_min: null,
    age_max: null,
    person_filters: {},
    person_covariates: ["age"],
    features: [],
  };
}

function saveDraft() {
  // Kept in this browser only, so a refresh does not lose work. Some
  // browsers refuse storage (private windows); the draft is then not kept.
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.study));
  } catch {
    // Nothing to do.
  }
}

function loadDraft() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch {
    return null;
  }
}

function setStudy(study) {
  state.study = { ...newStudy(), ...study };
  saveDraft();
  renderAll();
}

function studyChanged() {
  saveDraft();
  renderFeatureLists();
  scheduleCheck();
}

function sourceOf(name) {
  return state.meta.sources.find((s) => s.name === name) || null;
}

function featureLabel(name) {
  const feature = state.study.features.find((f) => f.name === name);
  return feature ? feature.label : name;
}


// ------------------------------------------------- design check and counts

let checkTimer = null;
let checkRound = 0;

function scheduleCheck() {
  // Wait for a pause in typing before asking the server.
  clearTimeout(checkTimer);
  checkTimer = setTimeout(checkStudy, 300);
}

async function checkStudy() {
  // Quick edits start several rounds; only the latest round's answers are
  // shown, in whatever order the responses arrive.
  const round = ++checkRound;
  const study = structuredClone(state.study);
  const [check, attrition] = await Promise.allSettled([
    api("/api/study/check", study),
    api("/api/attrition", study),
  ]);
  if (round !== checkRound) return;

  if (check.status === "fulfilled") {
    state.issues = check.value.issues;
    renderModel(check.value.model);
  } else {
    state.issues = check.reason.issues.length ? check.reason.issues
      : [{ level: "error", code: "request_failed", message: check.reason.message, feature: null }];
    renderModel(null);
  }
  renderIssues();
  renderFeatureLists();
  renderAttrition(attrition);
}

function renderIssues() {
  const list = $("issues");
  if (state.issues.length === 0) {
    list.replaceChildren(el("li", { class: "ok" }, "No problems found."));
  } else {
    list.replaceChildren(...issueItems(state.issues, featureLabel));
  }
  // An analysis with design errors would be refused, so do not offer it.
  $("run").disabled = state.issues.some((i) => i.level === "error");
}

function renderModel(model) {
  $("model-name").textContent = model ? model.name : "Set an outcome to see which model will be used.";
  $("model-reason").textContent = model ? model.reason : "";
}

function renderAttrition(result) {
  const body = $("attrition");
  if (result.status === "rejected") {
    body.replaceChildren();
    $("count-treated").textContent = "–";
    $("count-control").textContent = "–";
    const message = result.reason.issues.length
      ? "Counts appear once the design errors are fixed."
      : `Counts are not available: ${result.reason.message}`;
    $("attrition-note").textContent = message;
    $("count-note").textContent = message;
    return;
  }

  const { steps, issues } = result.value;
  const rows = [];
  for (const step of steps) {
    rows.push(el("tr", {}, el("td", {}, step.step),
      el("td", {}, formatCount(step.treated)), el("td", {}, formatCount(step.control))));
  }
  body.replaceChildren(...rows);
  const last = steps[steps.length - 1];
  $("count-treated").textContent = formatCount(last.treated);
  $("count-control").textContent = formatCount(last.control);

  const small = issues.filter((i) => i.code === "small_cell").length;
  const note = small
    ? `${small} of these counts are below the suppression threshold of 5. Do not share them as they are.`
    : "";
  $("attrition-note").textContent = note;
  $("count-note").textContent = small ? "Some counts are below 5; see the table in step 1." : "After every eligibility step.";
}


// ------------------------------------------------------- step 1: cohort

function renderAll() {
  const exposure = $("exposure");
  exposure.replaceChildren();
  for (const x of state.meta.exposures) exposure.append(el("option", { value: x.name }, x.label));
  exposure.value = state.study.exposure;
  $("seed").value = state.study.seed;
  $("age-min").value = state.study.age_min ?? "";
  $("age-max").value = state.study.age_max ?? "";
  renderPersonFilters();
  renderPersonCovariates();
  renderFeatureLists();
  scheduleCheck();
}

// Checkboxes for a list of values. onChange gets the ticked values.
function checkboxes(values, selected, onChange, display = (v) => v) {
  const inputs = [];
  const labels = [];
  for (const value of values) {
    const input = el("input", { type: "checkbox", value });
    input.checked = selected.includes(value);
    input.addEventListener("change", () => {
      onChange(inputs.filter((i) => i.checked).map((i) => i.value));
    });
    inputs.push(input);
    labels.push(el("label", { class: "check" }, input, display(value)));
  }
  return labels;
}

function renderPersonFilters() {
  const box = $("person-filters");
  box.replaceChildren();
  for (const attribute of state.meta.person_attributes) {
    const checks = el("div", { class: "checks" }, el("span", { class: "hint" }, "Loading..."));
    box.append(el("fieldset", {}, el("legend", {}, readable(attribute)), checks));
    valuesOf("person", attribute).then((values) => {
      const selected = state.study.person_filters[attribute] || [];
      checks.replaceChildren(...checkboxes(values, selected, (chosen) => {
        if (chosen.length) state.study.person_filters[attribute] = chosen;
        else delete state.study.person_filters[attribute];
        studyChanged();
      }));
    }).catch((error) => {
      checks.replaceChildren(el("span", { class: "hint" }, `Could not load values: ${error.message}`));
    });
  }
}

function renderPersonCovariates() {
  $("person-covariates").replaceChildren(...checkboxes(
    state.meta.person_covariates, state.study.person_covariates,
    (chosen) => {
      state.study.person_covariates = chosen;
      studyChanged();
    },
    readable));
}


// ---------------------------------------------- the lists of features

function renderFeatureLists() {
  for (const role of ["inclusion", "covariate", "outcome"]) {
    const items = [];
    state.study.features.forEach((f, index) => {
      if (f.role !== role) return;
      const issues = state.issues.filter((i) => i.feature === f.name);
      items.push(el("li", { class: "feature" },
        el("div", { class: "feature-text" },
          el("div", { class: "feature-title" }, f.label),
          el("div", { class: "feature-description" }, describe(f)),
          issues.length ? el("ul", { class: "issues" }, ...issueItems(issues)) : null),
        el("button", { type: "button", class: "link", "aria-label": `Edit ${f.label}`,
          onclick: () => openFeature(role, index) }, "Edit"),
        el("button", { type: "button", class: "link", "aria-label": `Remove ${f.label}`,
          onclick: () => removeFeature(index) }, "Remove")));
    });
    $(`list-${role}`).replaceChildren(...items);
  }
  $("add-outcome").hidden = state.study.features.some((f) => f.role === "outcome");
}

function removeFeature(index) {
  const feature = state.study.features[index];
  if (!window.confirm(`Remove "${feature.label}"?`)) return;
  state.study.features.splice(index, 1);
  studyChanged();
}

// One line saying what a feature counts, in words.
function describe(f) {
  const source = sourceOf(f.source);
  const parts = [source ? source.label : f.source];
  for (const [dimension, values] of Object.entries(f.filters || {})) {
    const found = source && source.dimensions.find((d) => d.name === dimension);
    parts.push(`${found ? found.label : dimension}: ${values.join(", ")}`);
  }
  if (MEASURE_AGGREGATIONS.includes(f.aggregation)) {
    const measure = source && source.measures.find((m) => m.name === f.measure);
    parts.push(`${f.aggregation} of ${measure ? measure.label : f.measure}`);
  } else {
    parts.push((AGGREGATION_LABELS[f.aggregation] || f.aggregation).toLowerCase());
  }
  parts.push(windowText(f.window, source));
  if (f.periodise) parts.push(`in ${f.periodise.n} periods of a ${f.periodise.grain}`);
  if (f.keep_if) {
    const op = OPERATORS.find(([code]) => code === f.keep_if.op);
    parts.push(`keep if ${op ? op[1] : f.keep_if.op} ${f.keep_if.value}`);
  }
  return parts.join(" · ");
}

function windowText(w, source) {
  const anchor = source && source.granularity === "year" ? "the index year" : "the index date";
  if (w.to <= -1) return `${-w.to} to ${-w.from} ${w.unit} before ${anchor}`;
  if (w.from >= 1) return `${w.from} to ${w.to} ${w.unit} after ${anchor}`;
  return `${w.from} to ${w.to} ${w.unit} around ${anchor}`;
}


// ------------------------------------------------- the feature dialog

function defaultFeature(role) {
  // Inclusion criteria usually test a condition; covariates and outcomes
  // usually count events. Pick a source to match.
  const sources = state.meta.sources;
  let source = sources[0];
  if (role === "inclusion") {
    source = sources.find((s) => s.name === "condition") || source;
  } else {
    source = sources.find((s) => s.granularity !== "year") || source;
  }
  const [, from, to, unit] = presetsFor(role, source)[0];
  const feature = {
    name: "", label: "", source: source.name, filters: {},
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

function unitsFor(source) {
  // Windows cannot be finer than what the source records.
  if (source.granularity === "year") return ["years"];
  if (source.granularity === "month") return ["months", "years"];
  return state.meta.window_units;
}

function presetsFor(role, source) {
  const before = role !== "outcome";
  let presets;
  if (source.granularity === "year") {
    presets = before
      ? [["Any year before the index year", -50, -1, "years"], ["The year before the index year", -1, -1, "years"]]
      : [["The year after the index year", 1, 1, "years"], ["Two years after", 1, 2, "years"]];
  } else {
    presets = before
      ? [["12 months before", -12, -1, "months"], ["30 days before", -30, -1, "days"], ["2 years before", -24, -1, "months"]]
      : [["12 months after", 1, 12, "months"], ["30 days after", 1, 30, "days"], ["2 years after", 1, 24, "months"]];
  }
  const units = unitsFor(source);
  return presets.filter((p) => units.includes(p[3]));
}

function aggregationsFor(role, source) {
  const allowed = [];
  for (const a of state.meta.aggregations) {
    const needsMeasure = MEASURE_AGGREGATIONS.includes(a.name);
    if (needsMeasure && !source.measures.some((m) => m.aggregations.includes(a.name))) continue;
    // No model is defined for a summed or averaged measure as the outcome.
    if (needsMeasure && role === "outcome") continue;
    // Time to event needs exact dates and is only ever an outcome.
    if (a.name === "time_to_first" && (role !== "outcome" || source.granularity !== "day")) continue;
    allowed.push(a);
  }
  return allowed;
}

function nameFor(label) {
  // The column name is made from the label, so nobody has to type one.
  let base = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 50);
  base = base.replace(/_+$/, "");
  if (!/^[a-z]/.test(base)) base = `f_${base}`.replace(/_+$/, "");
  const taken = new Set(RESERVED.concat(state.meta.person_attributes));
  state.study.features.forEach((f, index) => {
    if (!state.editing || index !== state.editing.index) taken.add(f.name);
  });
  let name = base;
  let k = 2;
  while (taken.has(name)) {
    name = `${base}_${k}`;
    k += 1;
  }
  return name;
}

function openFeature(role, index = null) {
  state.editing = { role, index };
  const existing = index === null ? null : state.study.features[index];
  const f = existing ? structuredClone(existing) : defaultFeature(role);

  $("feature-title").textContent = `${existing ? "Edit" : "New"} ${ROLE_NAMES[role]}`;
  $("f-label").value = f.label;
  const sourceSelect = $("f-source");
  sourceSelect.replaceChildren();
  for (const s of state.meta.sources) sourceSelect.append(el("option", { value: s.name }, s.label));
  sourceSelect.value = f.source;
  $("f-from").value = f.window.from;
  $("f-to").value = f.window.to;

  const grain = $("f-grain");
  grain.replaceChildren();
  for (const g of state.meta.period_grains) grain.append(el("option", { value: g }, g));
  $("f-periodise").checked = Boolean(f.periodise);
  grain.value = f.periodise ? f.periodise.grain : "quarter";
  $("f-n").value = f.periodise ? f.periodise.n : 4;

  const op = $("f-op");
  op.replaceChildren();
  for (const [code, words] of OPERATORS) op.append(el("option", { value: code }, words));
  op.value = f.keep_if ? f.keep_if.op : "==";
  $("f-value").value = f.keep_if ? f.keep_if.value : 1;

  sourceChanged(f);
  $("f-preview").replaceChildren();
  $("f-name").textContent = nameFor(f.label);
  $("feature-dialog").showModal();
  $("f-label").focus();
}

// Fill everything that depends on the source. keep holds the values to
// keep where they are still allowed (when editing an existing feature).
function sourceChanged(keep = null) {
  const role = state.editing.role;
  const source = sourceOf($("f-source").value);

  const unit = $("f-unit");
  const previousUnit = keep ? keep.window.unit : unit.value;
  unit.replaceChildren();
  for (const u of unitsFor(source)) unit.append(el("option", { value: u }, u));
  if (unitsFor(source).includes(previousUnit)) unit.value = previousUnit;

  const presets = [];
  for (const [label, from, to, presetUnit] of presetsFor(role, source)) {
    presets.push(el("button", { type: "button", onclick: () => {
      $("f-from").value = from;
      $("f-to").value = to;
      $("f-unit").value = presetUnit;
    } }, label));
  }
  $("f-presets").replaceChildren(...presets);

  const timing = role === "outcome"
    ? "Outcomes are counted after the index date, so 'from' is usually 1 or more."
    : "Must end before the index date: 'to' is -1 or earlier.";
  const counting = source.granularity === "year"
    ? " This source only records the year, so the window counts calendar years from the index year."
    : " Negative numbers are before the index date; 0 is the index day itself.";
  $("f-window-hint").textContent = timing + counting;

  const aggregation = $("f-aggregation");
  const previousAggregation = keep ? keep.aggregation : aggregation.value;
  aggregation.replaceChildren();
  const allowed = aggregationsFor(role, source);
  for (const a of allowed) aggregation.append(el("option", { value: a.name }, AGGREGATION_LABELS[a.name] || a.name));
  if (allowed.some((a) => a.name === previousAggregation)) aggregation.value = previousAggregation;

  aggregationChanged(keep ? keep.measure : null);
  renderDialogFilters(source, keep ? keep.filters : {});
}

function aggregationChanged(keepMeasure = null) {
  const source = sourceOf($("f-source").value);
  const name = $("f-aggregation").value;
  const description = state.meta.aggregations.find((a) => a.name === name);
  $("f-aggregation-hint").textContent = description ? description.description : "";

  const measure = $("f-measure");
  measure.replaceChildren();
  for (const m of source.measures) {
    if (m.aggregations.includes(name)) measure.append(el("option", { value: m.name }, m.label));
  }
  if (keepMeasure) measure.value = keepMeasure;
  updateDialogVisibility();
}

function updateDialogVisibility() {
  const role = state.editing.role;
  const aggregation = $("f-aggregation").value;
  $("f-measure-field").hidden = !MEASURE_AGGREGATIONS.includes(aggregation);
  // A criterion needs one value per patient, and time to event is one value.
  $("f-periods").hidden = role === "inclusion" || aggregation === "time_to_first";
  $("f-period-fields").hidden = !$("f-periodise").checked;
  $("f-keep").hidden = role !== "inclusion";
}

function renderDialogFilters(source, selected) {
  const box = $("f-filters");
  box.replaceChildren();
  for (const dimension of source.dimensions) {
    const checks = el("div", { class: "checks" }, el("span", { class: "hint" }, "Loading..."));
    box.append(el("fieldset", { "data-dimension": dimension.name },
      el("legend", {}, `${dimension.label} (nothing ticked means any)`), checks));
    valuesOf(source.name, dimension.name).then((values) => {
      // The user may have picked another source while this loaded.
      if ($("f-source").value !== source.name) return;
      checks.replaceChildren(...checkboxes(values, selected[dimension.name] || [], () => {}));
    }).catch((error) => {
      checks.replaceChildren(el("span", { class: "hint" }, `Could not load values: ${error.message}`));
    });
  }
}

function wholeNumber(id) {
  const n = Number.parseInt($(id).value, 10);
  return Number.isNaN(n) ? null : n;
}

function readFeature() {
  const role = state.editing.role;
  const filters = {};
  for (const fieldset of $("f-filters").querySelectorAll("fieldset[data-dimension]")) {
    const ticked = [];
    for (const box of fieldset.querySelectorAll("input:checked")) ticked.push(box.value);
    if (ticked.length) filters[fieldset.dataset.dimension] = ticked;
  }
  const feature = {
    name: $("f-name").textContent,
    label: $("f-label").value.trim(),
    source: $("f-source").value,
    filters,
    window: { anchor: "index", from: wholeNumber("f-from"), to: wholeNumber("f-to"), unit: $("f-unit").value },
    aggregation: $("f-aggregation").value,
    role,
  };
  if (MEASURE_AGGREGATIONS.includes(feature.aggregation)) feature.measure = $("f-measure").value;
  if (!$("f-periods").hidden && $("f-periodise").checked) {
    feature.periodise = { grain: $("f-grain").value, n: wholeNumber("f-n") };
  }
  if (role === "inclusion") {
    feature.keep_if = { op: $("f-op").value, value: Number($("f-value").value) };
  }
  return feature;
}

async function previewFeature() {
  const box = $("f-preview");
  if (!$("f-label").value.trim()) {
    box.replaceChildren(el("p", {}, "Give the feature a name first."));
    return;
  }
  box.replaceChildren(el("p", { class: "hint" }, "Counting..."));
  try {
    const summary = await api("/api/preview", { feature: readFeature(), study: state.study });
    const rows = [];
    for (const column of summary.columns) {
      for (const group of ["treated", "control"]) {
        const s = column[group];
        rows.push([column.column, group === "treated" ? "Treated" : "Controls", formatCount(s.n),
          formatCount(s.nonzero), formatNumber(s.mean), formatNumber(s.min), formatNumber(s.max)]);
      }
    }
    box.replaceChildren(
      numberTable(["Column", "Group", "Patients", "Non-zero", "Mean", "Min", "Max"], rows),
      summary.issues.length ? el("ul", { class: "issues" }, ...issueItems(summary.issues)) : null);
  } catch (error) {
    box.replaceChildren(el("p", {}, error.message),
      el("ul", { class: "issues" }, ...issueItems(error.issues)));
  }
}

function saveFeature(event) {
  event.preventDefault();
  if (!$("f-label").value.trim()) {
    $("f-preview").replaceChildren(el("p", {}, "Give the feature a name."));
    $("f-label").focus();
    return;
  }
  const feature = readFeature();
  const features = state.study.features;
  if (state.editing.index !== null) {
    features[state.editing.index] = feature;
  } else {
    if (feature.role === "outcome") {
      // One outcome per study: a new one replaces the old.
      state.study.features = features.filter((f) => f.role !== "outcome");
    }
    state.study.features.push(feature);
  }
  $("feature-dialog").close();
  studyChanged();
}


// -------------------------------------------------------- the analysis

async function runAnalysis() {
  showStep("results");
  const button = $("run");
  button.disabled = true;
  setResultsBusy(true);
  try {
    const result = await api("/api/analysis", state.study);
    renderResults(result, structuredClone(state.study));
  } catch (error) {
    renderResultsError(error);
  } finally {
    setResultsBusy(false);
    renderIssues();
  }
}


// --------------------------------------------------------- files, tabs

function downloadStudy() {
  const blob = new Blob([JSON.stringify(state.study, null, 2)], { type: "application/json" });
  const link = el("a", { href: URL.createObjectURL(blob), download: "study.json" });
  link.click();
  URL.revokeObjectURL(link.href);
}

async function openStudyFile(file) {
  try {
    setStudy(JSON.parse(await file.text()));
  } catch (error) {
    showBanner(`Could not open ${file.name}: ${error.message}`);
  }
}

function showBanner(message) {
  const banner = $("load-error");
  banner.textContent = message;
  banner.hidden = false;
}

function showStep(step) {
  for (const name of ["cohort", "features", "results"]) {
    $(`tab-${name}`).setAttribute("aria-selected", String(name === step));
    $(`panel-${name}`).hidden = name !== step;
  }
}


// ------------------------------------------------------------- start

function wireEvents() {
  for (const name of ["cohort", "features", "results"]) {
    $(`tab-${name}`).addEventListener("click", () => showStep(name));
  }
  $("exposure").addEventListener("change", (e) => {
    state.study.exposure = e.target.value;
    studyChanged();
  });
  $("seed").addEventListener("input", (e) => {
    state.study.seed = Math.max(0, Number.parseInt(e.target.value, 10) || 0);
    studyChanged();
  });
  for (const [id, key] of [["age-min", "age_min"], ["age-max", "age_max"]]) {
    $(id).addEventListener("input", (e) => {
      const n = Number.parseInt(e.target.value, 10);
      state.study[key] = Number.isNaN(n) ? null : n;
      studyChanged();
    });
  }
  for (const button of document.querySelectorAll("[data-add]")) {
    button.addEventListener("click", () => openFeature(button.dataset.add));
  }
  $("run").addEventListener("click", runAnalysis);
  $("new-study").addEventListener("click", () => {
    if (window.confirm("Start a new study? The current one is lost unless you saved it to a file.")) {
      setStudy(newStudy());
    }
  });
  $("save-study").addEventListener("click", downloadStudy);
  $("open-study").addEventListener("click", () => $("open-study-file").click());
  $("open-study-file").addEventListener("change", (e) => {
    if (e.target.files.length) openStudyFile(e.target.files[0]);
    e.target.value = "";
  });

  $("f-label").addEventListener("input", () => {
    $("f-name").textContent = nameFor($("f-label").value);
  });
  $("f-source").addEventListener("change", () => sourceChanged());
  $("f-aggregation").addEventListener("change", () => aggregationChanged());
  $("f-periodise").addEventListener("change", updateDialogVisibility);
  for (const button of document.querySelectorAll("[data-keep]")) {
    button.addEventListener("click", () => {
      const [op, value] = button.dataset.keep.split(",");
      $("f-op").value = op;
      $("f-value").value = value;
    });
  }
  $("f-preview-button").addEventListener("click", previewFeature);
  $("f-cancel").addEventListener("click", () => $("feature-dialog").close());
  $("feature-form").addEventListener("submit", saveFeature);
  $("feature-dialog").addEventListener("close", () => {
    state.editing = null;
  });
}

async function start() {
  wireEvents();
  try {
    state.meta = await api("/api/metadata");
  } catch (error) {
    showBanner(`Could not reach the server: ${error.message}`);
    return;
  }
  $("dataset").textContent = state.meta.dataset;
  setStudy(loadDraft() || newStudy());
}

start();
