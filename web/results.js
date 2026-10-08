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

export function setResultsBusy(busy) {
  // Keep the previous result visible but faded while a new one is computed,
  // rather than blanking the page.
  document.getElementById("results").classList.toggle("busy", busy);
}

export function renderResults(result, fromStudy) {
  shown = result;
  study = fromStudy;
  draw();
}

export function renderResultsError(error) {
  shown = null;
  destroyCharts();
  const box = document.getElementById("results");
  box.hidden = false;
  document.getElementById("results-empty").hidden = true;
  box.replaceChildren(el("div", { class: "card" },
    el("h2", {}, "The analysis could not be run"),
    el("p", {}, error.message),
    error.issues.length ? el("ul", { class: "issues" }, ...issueItems(error.issues)) : null));
}

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (shown) draw();
});

function draw() {
  destroyCharts();
  const box = document.getElementById("results");
  box.hidden = false;
  document.getElementById("results-empty").hidden = true;
  box.replaceChildren();
  // Each section adds itself to box before drawing its chart, because
  // Chart.js measures the canvas's container when it draws.
  headline(box, shown);
  cohortTiles(box, shown);
  warnings(box, shown);
  balanceChart(box, shown);
  propensityCharts(box, shown);
  survivalChart(box, shown);
  periodChart(box, shown);
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
  return p < 0.001 ? "p < 0.001" : `p = ${p.toFixed(3)}`;
}

function headline(box, r) {
  const m = r.model;
  box.append(el("div", { class: "card" },
    el("div", { class: "headline" },
      el("span", { class: "hero" }, formatNumber(m.estimate)),
      el("span", { class: "hero-label" },
        `${m.measure}, 95% CI ${formatNumber(m.ci_low)} to ${formatNumber(m.ci_high)}, ${pText(m.p_value)}`)),
    el("p", {}, r.interpretation),
    el("p", { class: "hint" }, m.reason)));
}

function tile(label, value, note = null) {
  return el("div", { class: "tile" },
    el("span", { class: "tile-label" }, label),
    el("span", { class: "tile-value" }, value),
    note ? el("span", { class: "hint" }, note) : null);
}

function cohortTiles(box, r) {
  const c = r.cohort;
  const unmatched = c.treated - c.treated_matched;
  let how = "Not matched: no covariates were chosen.";
  if (c.matched && unmatched === 0) {
    how = "Every treated patient was matched to one control with a similar propensity score.";
  } else if (c.matched) {
    how = "Treated patients were matched one to one with controls of similar propensity score. " +
      `${formatCount(unmatched)} had no close enough control and are left out.`;
  }
  box.append(el("div", { class: "card" },
    el("h2", {}, "Patients analysed"),
    el("div", { class: "result-tiles" },
      tile("Treated", formatCount(c.treated_matched), `of ${formatCount(c.treated)} in the cohort`),
      tile("Controls", formatCount(c.control_matched), `of ${formatCount(c.control)} in the cohort`),
      tile("Treated with the outcome", formatCount(r.events.treated)),
      tile("Controls with the outcome", formatCount(r.events.control))),
    el("p", { class: "hint" }, how)));
}

function warnings(box, r) {
  const body = r.issues.length
    ? el("ul", { class: "issues" }, ...issueItems(r.issues))
    : el("p", { class: "ok" }, "None.");
  box.append(el("div", { class: "card" }, el("h2", {}, "Warnings"), body));
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
  return el("details", {}, el("summary", {}, "Show the numbers"), numberTable(headers, rows));
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

  box.append(el("div", { class: "card" },
    el("h2", {}, "Covariate balance"),
    el("p", { class: "hint" }, "How different the groups are on each covariate, as a standardised mean " +
      "difference. Below 0.1, the vertical line, is usually taken as balanced."),
    legend([{ label: "Before matching", color: t.before, kind: "dot" },
            { label: "After matching", color: t.ink, kind: "dot" },
            { label: "0.1", color: t.muted, kind: "line" }]),
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
  box.append(el("div", { class: "card" },
    el("h2", {}, "Propensity score overlap"),
    el("p", { class: "hint" }, "Share of each group at each propensity score, the estimated chance of " +
      "being treated. Treated patients where hardly any controls lie have no good comparison. After " +
      "matching the two lines should nearly coincide."),
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
  box.append(el("div", { class: "card" },
    el("h2", {}, "Time to first event"),
    el("p", { class: "hint" }, "Share of each analysed group still without the event, by days since the " +
      "index date (Kaplan-Meier). The hazard ratio assumes these curves separate steadily; if they " +
      "cross or come together, one ratio summarises them poorly."),
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
  box.append(el("div", { class: "card" },
    el("h2", {}, "Outcome by period"),
    el("p", { class: "hint" }, "Mean per patient in each period, in the analysed groups. The rate ratio " +
      "above is the average gap between these lines, allowing for each patient's periods being related."),
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
