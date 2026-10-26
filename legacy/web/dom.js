// Small DOM helpers shared by the builder (app.js) and the results view
// (results.js). Text is always inserted as text and never parsed as HTML,
// because labels and values come from users and from the data.

// el("p", {class: "hint"}, "Some text", childNode) builds an element.
// Attributes named on... become event listeners.
export function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

// One <li> per issue, with its level written out so it never depends on colour.
// labelFor turns a feature name into its label, to say which feature an
// issue belongs to; leave it out where that is already clear.
export function issueItems(issues, labelFor = null) {
  const items = [];
  for (const issue of issues) {
    const badge = el("span", {class: `badge badge-${issue.level}`},
      issue.level === "error" ? "Error" : "Warning");
    let text = issue.message;
    if (labelFor && issue.feature) text = `${labelFor(issue.feature)}: ${issue.message}`;
    items.push(el("li", {}, badge, text));
  }
  return items;
}

// residence_status -> Residence status
export function readable(code) {
  const words = code.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function numberTable(headers, rows) {
  const head = el("tr", {});
  for (const header of headers) head.append(el("th", {scope: "col"}, header));
  const body = el("tbody", {});
  for (const row of rows) {
    const tr = el("tr", {});
    for (const cell of row) tr.append(el("td", {}, cell));
    body.append(tr);
  }
  return el("table", {class: "numbers"}, el("thead", {}, head), body);
}

export function formatNumber(x, digits = 2) {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  return x.toFixed(digits);
}

export function formatCount(n) {
  if (n === null || n === undefined) return "–";
  return n.toLocaleString("en");
}

export function formatShare(x) {
  if (x === null || x === undefined) return "–";
  return `${(x * 100).toFixed(1)}%`;
}
