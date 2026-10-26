// The results view: the effect estimate, cohort sizes, warnings, and the
// charts a reader needs to judge whether to trust the estimate. Every chart
// has a table with the same numbers underneath it.
//
// Colours come from the CSS variables in style.css: blue for treated,
// orange for controls in every chart, grey for "before matching".
import { el, formatCount, formatNumber, formatShare, issueItems, numberTable, readable } from "./dom.js";

const charts = [];     // Chart.js instances, destroyed before each redraw
let shown = null;      // the result on screen, redrawn when the theme changes
let study = null;      // the study it came from, for feature labels
let exposure = "";     // the programme's label, for the answer sentence

export function setResultsBusy(busy) {
  // Keep the previous result visible but faded while a new one is computed,
  // rather than blanking the page.
  document.getElementById("results").classList.toggle("busy", busy);
}

export function renderResults(result, fromStudy, exposureLabel) {
  shown = result;
  study = fromStudy;
  exposure = exposureLabel;
  draw();
}

// Charts take their colours when drawn, so a theme change redraws them.
export function redrawResults() {
  if (shown) draw();
}

export function renderResultsError(error) {
  shown = null;
  destroyCharts();
  const box = document.getElementById("results");
  box.hidden = false;
  document.getElementById("results-empty").hidden = true;
  box.replaceChildren(el("div", { class: "answer" },
    el("span", { class: "eyebrow" }, "Step 3 · Results"),
    el("p", { class: "answer-sentence" }, "The analysis could not be run."),
    el("p", {}, error.message),
    error.issues.length ? el("ul", { class: "issues" }, ...issueItems(error.issues)) : null));
}

function draw() {
  destroyCharts();
  const box = document.getElementById("results");
  box.hidden = false;
  document.getElementById("results-empty").hidden = true;
  box.replaceChildren();
  // The answer first, then whether to trust it, then the detail. Each
  // section adds itself to box before drawing its chart, because Chart.js
  // measures the canvas's container when it draws.
  answer(box, shown);
  cohortTiles(box, shown);
  trust(box, shown);
  box.append(el("h2", { class: "section-title" }, "Detail"));
  balanceChart(box, shown);
  propensityCharts(box, shown);
  survivalChart(box, shown);
  periodChart(box, shown);
  box.append(el("p", { class: "model-note" }, shown.interpretation));
}

function destroyCharts() {
  while (charts.length) charts.pop().destroy();
}


// --------------------------------------------------------------- text

// The label a researcher gave a covariate, rather than its column name.
function covariateLabel(column) {
  if (column === "age") return "Age";
  if (column.includes("=")) {
    // A category of a patient attribute, such as gender=M.
    const [attribute, level] = column.split("=");
    return `${readable(attribute)}: ${level}`;
  }
  for (const f of study.features) {
    if (f.name === column) return f.label;
    const period = column.slice(f.name.length + 2);
    if (column.startsWith(`${f.name}_p`) && /^[0-9]+$/.test(period)) return `${f.label}, period ${period}`;
  }
  return column;
}

function pText(p) {
  return p < 0.001 ? "< 0.001" : p.toFixed(3);
}

// "17% lower" or "4% higher" for a ratio.
function change(ratio) {
  const pct = Math.round(Math.abs(1 - ratio) * 100);
  return ratio < 1 ? `${pct}% lower` : `${pct}% higher`;
}

// Ticks at a round step across [min, max].
function ticks(min, max) {
  const raw = (max - min) / 5;
  const step = [0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10].find((s) => s >= raw) || raw;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(Number(v.toFixed(4)));
  return out;
}

// The headline: the answer as a sentence, the estimate, and its interval
// drawn against the line of no difference.
function answer(box, r) {
  const m = r.model;
  const outcome = study.features.find((f) => f.role === "outcome");
  const what = { "Odds ratio": "odds", "Rate ratio": "rate", "Hazard ratio": "rate" }[m.measure] || "value";
  const includesOne = m.ci_low <= 1 && m.ci_high >= 1;
  const noChange = Math.round(Math.abs(1 - m.estimate) * 100) === 0;
  const subject = `Patients in ${exposure}`;
  const compared = r.cohort.matched ? "similar patients who weren't enrolled" : "patients who weren't enrolled";
  const label = outcome.label.charAt(0).toLowerCase() + outcome.label.slice(1);
  let sentence = noChange
    ? `${subject} had about the same ${what} of ${label} as ${compared}`
    : `${subject} had a ${change(m.estimate)} ${what} of ${label} than ${compared}`;
  sentence += includesOne && !noChange ? ", but the data are also consistent with no difference." : ".";

  const lo = Math.min(m.ci_low, 1);
  const hi = Math.max(m.ci_high, 1);
  const pad = (hi - lo) * 0.25 || 0.1;
  const min = Math.max(0, lo - pad);
  const max = hi + pad;
  const at = (v) => `${((v - min) / (max - min)) * 100}%`;
  const pairs = r.cohort.matched ? `${formatCount(r.cohort.treated_matched)} matched pairs` : "not matched";

  box.append(el("section", { class: "answer", "aria-label": "Answer" },
    el("div", { class: "answer-top" },
      el("span", { class: "eyebrow" }, "Step 3 · The answer"),
      el("span", { class: "hint" }, `${outcome.label} · ${pairs}`)),
    el("p", { class: "answer-sentence" }, sentence),
    el("div", { class: "figures" },
      el("div", { class: "figure" }, el("span", {}, m.measure), el("span", { class: "big" }, formatNumber(m.estimate))),
      el("div", { class: "figure" }, el("span", {}, "95% confidence interval"),
        el("span", { class: "mid" }, `${formatNumber(m.ci_low)} to ${formatNumber(m.ci_high)}`)),
      el("div", { class: "figure" }, el("span", {}, "p-value"), el("span", { class: "mid" }, pText(m.p_value))),
      el("span", { class: "significance" }, m.p_value < 0.05 ? "Statistically significant at 0.05" : "Not statistically significant at 0.05")),
    el("figure", { class: "ci", "aria-label": `${m.measure} ${formatNumber(m.estimate)} with 95% interval ${formatNumber(m.ci_low)} to ${formatNumber(m.ci_high)}, where 1 means no difference` },
      el("div", { class: "ci-track" },
        el("div", { class: "line" }),
        el("div", { class: "null", style: `left:${at(1)}` }),
        el("div", { class: "range", style: `left:${at(m.ci_low)};width:calc(${at(m.ci_high)} - ${at(m.ci_low)})` }),
        el("div", { class: "point", style: `left:${at(m.estimate)}` })),
      el("div", { class: "ci-ticks", "aria-hidden": "true" },
        ...ticks(min, max).map((v) => el("span", { class: Math.abs(v - 1) < 1e-9 ? "one" : null, style: `left:${at(v)}` }, v.toFixed(2)))),
      el("div", { class: "ci-sides" },
        el("span", {}, `← Lower with ${exposure}`), el("span", {}, `Higher with ${exposure} →`)),
      el("figcaption", {}, "The plausible effect ranges from ", el("strong", {}, change(m.ci_low)),
        " to ", el("strong", {}, change(m.ci_high)), ". ",
        includesOne ? "Because that range includes no difference, this study can't rule out chance."
          : "That range excludes no difference, so chance alone is an unlikely explanation."))));
}

function tile(label, value, note = null, key = null) {
  return el("div", { class: "result-tile" },
    el("span", { class: "tile-label" }, key ? el("span", { class: `key key-${key}` }) : null, label),
    el("span", { class: "tile-value" }, value),
    note ? el("span", { class: "hint" }, note) : null);
}

function cohortTiles(box, r) {
  const c = r.cohort;
  box.append(el("div", { class: "result-tiles" },
    tile(c.matched ? "Treated, matched" : "Treated", formatCount(c.treated_matched), `of ${formatCount(c.treated)} eligible`, "treated"),
    tile(c.matched ? "Controls, matched" : "Controls", formatCount(c.control_matched), `from a pool of ${formatCount(c.control)}`, "control"),
    tile("Treated with the outcome", formatCount(r.events.treated)),
    tile("Controls with the outcome", formatCount(r.events.control))));
}

function check(ok, title, text) {
  return el("li", { class: ok ? null : "warn" },
    ok ? el("span", { class: "tick", "aria-label": "Passed" }, "✓") : el("span", { class: "badge badge-warning" }, "Warning"),
    el("span", {}, el("strong", {}, title), el("span", { class: "text" }, text)));
}

// What a reader should check before believing the estimate.
function trust(box, r) {
  const c = r.cohort;
  const items = [];
  if (r.balance.length) {
    const worst = r.balance.reduce((a, b) => (Math.abs(b.smd_after) > Math.abs(a.smd_after) ? b : a));
    items.push(Math.abs(worst.smd_after) < 0.1
      ? check(true, "Groups are balanced", `All ${r.balance.length} characteristics under 0.1 standardised difference${c.matched ? " after matching" : ""}.`)
      : check(false, "Groups still differ", `Largest standardised difference: ${Math.abs(worst.smd_after).toFixed(2)} (${covariateLabel(worst.covariate)}).`));
  }
  const unmatched = c.treated - c.treated_matched;
  if (!c.matched) {
    items.push(check(false, "Groups were not matched", "No covariates were chosen, so the groups are compared as they are."));
  } else if (unmatched === 0) {
    items.push(check(true, "Every treated patient was matched", "Each has one control with a similar propensity score."));
  } else {
    items.push(check(false, `${formatCount(unmatched)} treated patients dropped`,
      `No close enough control. The result applies to the ${Math.round(c.treated_matched / c.treated * 100)}% who were matched.`));
  }
  for (const issue of r.issues) {
    items.push(el("li", { class: "warn" },
      el("span", { class: `badge badge-${issue.level}` }, issue.level === "error" ? "Error" : "Warning"),
      el("span", { class: "text" }, issue.message)));
  }
  box.append(el("h2", { class: "section-title" }, "Can I trust this?"), el("ul", { class: "trust" }, ...items));
}

// A detail section: title and legend in the head, the chart, and its numbers.
function chartCard(title, hint, legendNode, body, table) {
  return el("section", { class: "card flush" },
    el("div", { class: "card-head" }, el("h3", {}, title), legendNode),
    el("div", { class: "chart-body" }, hint ? el("p", { class: "hint" }, hint) : null, body),
    table);
}


// ------------------------------------------------------------- charts

function theme() {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  return {
    treated: v("--treated"), control: v("--control"), before: v("--before"),
    ink: v("--ink"), ink2: v("--ink-2"), muted: v("--muted"),
    grid: v("--grid"), axis: v("--axis"), surface: v("--surface"),
    font: getComputedStyle(document.body).fontFamily,
  };
}

// The legend is drawn in HTML above the chart: its text stays in the ink
// colours and the coloured key beside it carries identity.
function legend(items) {
  const keys = [];
  for (const item of items) {
    const key = item.kind === "dot"
      ? el("span", { class: "key", style: `background:${item.color}` })
      : el("span", { class: "line-key", style: `background:${item.color}` });
    keys.push(el("span", {}, key, item.label));
  }
  return el("div", { class: "legend" }, ...keys);
}

function chartBox(height) {
  const canvas = el("canvas", { role: "img" });
  return { canvas, node: el("div", { class: "chart", style: `height:${height}px` }, canvas) };
}

function tableView(headers, rows) {
  return el("details", {}, el("summary", {}, "Data table"), el("div", { class: "table-scroll" }, numberTable(headers, rows)));
}

function axis(t, title, extra = {}) {
  return {
    grid: { color: t.grid }, border: { color: t.axis },
    ticks: { color: t.muted, font: { family: t.font } },
    title: { display: Boolean(title), text: title, color: t.ink2, font: { family: t.font } },
    ...extra,
  };
}

// Options shared by every chart: no animation, a hover tooltip listing
// every series at the pointer's position, value first then series name.
function options(t, scales, format, extra = {}) {
  // valueAxis says which axis holds the values (x for the horizontal dot plot).
  const { valueAxis = "y", ...rest } = extra;
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: t.surface, borderColor: t.axis, borderWidth: 1,
        titleColor: t.ink, bodyColor: t.ink2, boxWidth: 12, boxHeight: 2,
        titleFont: { family: t.font }, bodyFont: { family: t.font },
        callbacks: { label: (item) => ` ${format(item.parsed[valueAxis])}  ${item.dataset.label}` },
        filter: (item) => !item.dataset.noTooltip,
      },
    },
    scales,
    ...rest,
  };
}

function line(label, data, color, extra = {}) {
  return {
    label, data, borderColor: color, backgroundColor: color, borderWidth: 2,
    borderCapStyle: "round", borderJoinStyle: "round", pointRadius: 0, pointHoverRadius: 4,
    ...extra,
  };
}


// A dot plot of each covariate's standardised mean difference before and
// after matching (a "Love plot"). Largest imbalance before matching at the top.
function balanceChart(box, r) {
  if (!r.balance.length) return;
  const t = theme();
  const rows = [...r.balance].sort((a, b) => Math.abs(b.smd_before) - Math.abs(a.smd_before));
  const names = rows.map((b) => covariateLabel(b.covariate));
  const before = rows.map((b) => Math.abs(b.smd_before));
  const after = rows.map((b) => Math.abs(b.smd_after));
  const { canvas, node } = chartBox(Math.max(180, 26 * names.length + 70));

  box.append(chartCard("Balance before and after matching",
    "How different the groups are on each covariate, as a standardised mean " +
      "difference. Below 0.1, the vertical line, is usually taken as balanced.",
    legend([{ label: "Before matching", color: t.before, kind: "dot" },
            { label: "After matching", color: t.ink, kind: "dot" },
            { label: "0.1 threshold", color: t.muted, kind: "line" }]),
    node,
    tableView(["Covariate", "Treated mean before", "Control mean before", "Difference before",
               "Treated mean after", "Control mean after", "Difference after"],
      rows.map((b) => [covariateLabel(b.covariate), formatNumber(b.treated_mean_before), formatNumber(b.control_mean_before),
        formatNumber(b.smd_before), formatNumber(b.treated_mean_after),
        formatNumber(b.control_mean_after), formatNumber(b.smd_after)]))));

  const dot = { showLine: false, pointRadius: 5, pointHoverRadius: 7, pointBorderColor: t.surface,
                pointBorderWidth: 2, pointHitRadius: 12 };
  charts.push(new Chart(canvas, {
    type: "line",
    data: {
      labels: names,
      datasets: [
        line("Before matching", before, t.before, { ...dot, pointBackgroundColor: t.before }),
        line("After matching", after, t.ink, { ...dot, pointBackgroundColor: t.ink }),
        line("0.1", names.map(() => 0.1), t.muted, { borderWidth: 1, pointHoverRadius: 0, noTooltip: true }),
      ],
    },
    options: options(t, {
      x: axis(t, "Absolute standardised mean difference", { min: 0, suggestedMax: 0.3 }),
      y: axis(t, "", { grid: { display: false } }),
    }, (v) => v.toFixed(3), { indexAxis: "y", valueAxis: "x", interaction: { mode: "index", axis: "y", intersect: false } }),
  }));
}


// The propensity score distribution of each group, before and after
// matching, side by side on the same scale.
function propensityCharts(box, r) {
  const p = r.plots && r.plots.propensity;
  if (!p) return;
  const t = theme();
  // Each band is plotted at its midpoint.
  const middles = [];
  for (let i = 0; i < p.edges.length - 1; i += 1) middles.push((p.edges[i] + p.edges[i + 1]) / 2);
  const points = (values) => middles.map((x, i) => ({ x, y: values[i] }));
  const top = Math.max(...p.before.treated, ...p.before.control, ...p.after.treated, ...p.after.control);

  const pair = el("div", { class: "chart-pair" });
  const boxes = [];
  for (const [stage, title] of [["before", "Before matching"], ["after", "After matching"]]) {
    const { canvas, node } = chartBox(240);
    pair.append(el("div", {}, el("h3", {}, title), node));
    boxes.push([stage, canvas]);
  }
  const rows = middles.map((x, i) => [`${p.edges[i].toFixed(2)} to ${p.edges[i + 1].toFixed(2)}`, formatShare(p.before.treated[i]), formatShare(p.before.control[i]),
    formatShare(p.after.treated[i]), formatShare(p.after.control[i])]);
  box.append(chartCard("Propensity scores",
    "Share of each group at each propensity score, the estimated chance of " +
      "being treated. Treated patients where hardly any controls lie have no good comparison. After " +
      "matching the two lines should nearly coincide.",
    legend([{ label: "Treated", color: t.treated, kind: "line" }, { label: "Controls", color: t.control, kind: "line" }]),
    pair,
    tableView(["Propensity score", "Treated before", "Controls before", "Treated after", "Controls after"], rows)));

  for (const [stage, canvas] of boxes) {
    charts.push(new Chart(canvas, {
      type: "line",
      data: { datasets: [line("Treated", points(p[stage].treated), t.treated),
                         line("Controls", points(p[stage].control), t.control)] },
      options: options(t, {
        x: axis(t, "Propensity score", { type: "linear", min: 0, max: p.edges[p.edges.length - 1] }),
        y: axis(t, "Share of group", { min: 0, max: Math.ceil(top * 20) / 20,
          ticks: { color: t.muted, callback: (v) => `${Math.round(v * 100)}%`, font: { family: t.font } } }),
      }, formatShare),
    }));
  }
}


// Kaplan-Meier curves, for a time-to-first-event outcome.
function survivalChart(box, r) {
  const s = r.plots && r.plots.survival;
  if (!s) return;
  const t = theme();
  const { canvas, node } = chartBox(280);
  const points = (values) => s.days.map((day, i) => ({ x: day, y: values[i] }));
  box.append(chartCard("Time to first event",
    "Share of each analysed group still without the event, by days since the " +
      "index date (Kaplan-Meier). The hazard ratio assumes these curves separate steadily; if they " +
      "cross or come together, one ratio summarises them poorly.",
    legend([{ label: "Treated", color: t.treated, kind: "line" }, { label: "Controls", color: t.control, kind: "line" }]),
    node,
    tableView(["Day", "Treated without the event", "Controls without the event"],
      s.days.map((day, i) => [String(day), formatShare(s.treated[i]), formatShare(s.control[i])]))));

  charts.push(new Chart(canvas, {
    type: "line",
    data: { datasets: [
      line("Treated", points(s.treated), t.treated, { stepped: "before" }),
      line("Controls", points(s.control), t.control, { stepped: "before" }),
    ] },
    options: options(t, {
      x: axis(t, "Days since the index date", { type: "linear", min: 0, max: s.days[s.days.length - 1] }),
      y: axis(t, "Without the event", { max: 1,
        ticks: { color: t.muted, callback: (v) => `${Math.round(v * 100)}%`, font: { family: t.font } } }),
    }, formatShare),
  }));
}


// The mean outcome per patient in each period, for a periodised outcome.
function periodChart(box, r) {
  const p = r.plots && r.plots.periods;
  if (!p) return;
  const t = theme();
  const labels = p.periods.map((_, i) => `Period ${i + 1}`);
  const { canvas, node } = chartBox(260);
  box.append(chartCard("Outcome by period",
    "Mean per patient in each period, in the analysed groups. The rate ratio " +
      "above is the average gap between these lines, allowing for each patient's periods being related.",
    legend([{ label: "Treated", color: t.treated, kind: "line" }, { label: "Controls", color: t.control, kind: "line" }]),
    node,
    tableView(["Period", "Treated", "Controls"],
      labels.map((label, i) => [label, formatNumber(p.treated[i], 3), formatNumber(p.control[i], 3)]))));

  const marker = { pointRadius: 4, pointBorderColor: t.surface, pointBorderWidth: 2, pointHitRadius: 12 };
  charts.push(new Chart(canvas, {
    type: "line",
    data: { labels, datasets: [
      line("Treated", p.treated, t.treated, { ...marker, pointBackgroundColor: t.treated }),
      line("Controls", p.control, t.control, { ...marker, pointBackgroundColor: t.control }),
    ] },
    options: options(t, { x: axis(t, ""), y: axis(t, "Mean per patient", { min: 0 }) }, (v) => v.toFixed(3)),
  }));
}
