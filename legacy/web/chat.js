// Step 0: the study assistant. The user describes a study in words, the
// assistant drafts it through /api/chat, and "Review in builder" hands the
// draft to steps 1 and 2. Nothing runs from here: the analysis starts only
// from the Run button, after the user has looked at the study.
//
// The server keeps nothing between turns, so the whole conversation and the
// current draft are sent every time.
import { el, issueItems, readable } from "./dom.js";

const chat = {
  messages: [],   // [{role, content, ...}]; role and content are what /api/chat gets
  draft: null,    // the latest study the assistant proposed
  issues: [],     // its design issues
  model: null,    // the model its outcome implies
  ready: false,   // whether the assistant says it is complete
  busy: false,
  error: null,    // shown once, after a failed request
};

let options = null;
const $ = (id) => document.getElementById(id);

// api: the builder's fetch helper. describe(feature): one line in words.
// exposureLabel(name): the programme's label. review(study): load the study
// into the builder and show step 1. onChange({draft}): tell the step bar.
export function startChat(given) {
  options = given;
  $("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    send();
  });
  $("chat-input").addEventListener("keydown", (e) => {
    // Enter sends, Shift+Enter starts a new line.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  $("chat-reset").addEventListener("click", reset);
  for (const button of document.querySelectorAll("[data-example]")) {
    button.addEventListener("click", () => {
      $("chat-input").value = button.dataset.example;
      send();
    });
  }
  render();
}

async function send() {
  const input = $("chat-input");
  const text = input.value.trim();
  if (!text || chat.busy) return;
  chat.messages.push({ role: "user", content: text });
  input.value = "";
  chat.busy = true;
  render();
  try {
    const messages = chat.messages.map(({ role, content }) => ({ role, content }));
    const result = await options.api("/api/chat", { messages, draft: chat.draft });
    let content = result.reply;
    if (result.questions.length) content += "\n\n" + result.questions.map((q, i) => `${i + 1}. ${q}`).join("\n");
    chat.messages.push({ role: "assistant", content, status: result.status, questions: result.questions,
      reply: result.reply });
    if (result.draft) {
      chat.draft = result.draft;
      chat.issues = result.issues;
      chat.model = result.model;
      chat.ready = result.status === "ready";
    }
  } catch (error) {
    // Put the message back so it can be sent again.
    chat.messages.pop();
    input.value = text;
    chat.error = error.message;
  } finally {
    chat.busy = false;
    render();
    input.focus();
  }
}

function reset() {
  if (chat.messages.length && !window.confirm("Start the conversation over?")) return;
  chat.messages = [];
  chat.draft = null;
  chat.issues = [];
  chat.model = null;
  chat.ready = false;
  chat.error = null;
  render();
}

function render() {
  const started = chat.messages.length > 0 || chat.busy;
  $("ask-intro").hidden = started;
  $("ask-examples").hidden = started;
  $("thread-head").hidden = !started;
  $("composer-hint").textContent = started ? "The assistant drafts. You decide what runs."
    : "Enter to send · Shift+Enter for a new line";
  $("chat-input").placeholder = started ? "Answer, or ask for a change, e.g. \"use 6 months instead of 12\""
    : "Describe your study, e.g. which programme, which outcome, over what time…";

  const items = [];
  for (const m of chat.messages) {
    items.push(m.role === "user" ? el("li", { class: "msg-user" }, el("div", {}, m.content)) : assistantMessage(m));
  }
  if (chat.busy) items.push(assistant(el("p", { class: "thinking" }, "Thinking…")));
  if (chat.error) {
    items.push(assistant(el("div", { class: "notice error", role: "alert" },
      el("strong", {}, "Could not reach the assistant"), el("span", {}, chat.error))));
    chat.error = null;
  }
  if (chat.draft && !chat.busy) items.push(assistant(draftCard()));
  $("chat-log").replaceChildren(...items);
  $("chat-send").disabled = chat.busy;
  $("chat-log").lastElementChild?.scrollIntoView({ block: "nearest" });
  options.onChange({ draft: chat.draft !== null });
}

function assistant(...body) {
  return el("li", { class: "msg-assistant" },
    el("span", { class: "avatar", "aria-hidden": "true" }, "AI"),
    el("div", { class: "msg-body" }, el("span", { class: "who" }, "Assistant"), ...body));
}

function assistantMessage(m) {
  const paragraphs = m.reply.split(/\n{2,}/).filter(Boolean);
  if (m.status === "unsupported") {
    return assistant(el("div", { class: "notice" },
      el("strong", {}, "This dataset can't answer that"),
      ...paragraphs.map((p) => el("span", {}, p))));
  }
  const body = paragraphs.map((p) => el("p", {}, p));
  if (m.questions.length) {
    body.push(el("ol", { class: "questions" }, ...m.questions.map((q, i) =>
      el("li", {}, el("span", { class: "feature-num" }, String(i + 1)), el("span", {}, q)))));
    body.push(el("p", { class: "hint" }, "Answer by number, in any order. Skip any and the assistant uses the default it suggests."));
  }
  return assistant(...body);
}

function item(title, detail) {
  return el("div", { class: "draft-item" }, el("strong", {}, title), detail ? el("span", {}, detail) : null);
}

// The drafted study as a summary card, with the one way forward: review it
// in the builder.
function draftCard() {
  const study = chat.draft;
  const errors = chat.issues.filter((i) => i.level === "error");
  const firstQuestion = chat.messages.find((m) => m.role === "user");
  const covariates = study.features.filter((f) => f.role === "covariate");
  const matchedOn = study.person_covariates.length + covariates.length;

  const people = [];
  if (study.age_min !== null || study.age_max !== null) people.push(`aged ${study.age_min ?? 0} to ${study.age_max ?? "any"}`);
  for (const [attribute, values] of Object.entries(study.person_filters)) people.push(`${readable(attribute)}: ${values.join(", ")}`);
  const byRole = (role) => study.features.filter((f) => f.role === role).map((f) => item(f.label, options.describe(f)));

  const rows = [
    ["Treatment group", [item(options.exposureLabel(study.exposure),
      `Index date: enrolment date · controls never enrolled${people.length ? " · " + people.join(" · ") : ""}`)]],
    ["Inclusion criteria", byRole("inclusion").length ? byRole("inclusion") : [el("span", { class: "hint" }, "None: everyone is eligible")]],
    ["Adjusted for", [
      study.person_covariates.length ? el("div", { class: "chips" }, ...study.person_covariates.map((c) => el("span", { class: "chip" }, readable(c)))) : null,
      ...byRole("covariate")]],
    ["Outcome", byRole("outcome").length ? byRole("outcome") : [el("span", { class: "hint" }, "Not chosen yet")]],
    ["Design check", chat.issues.length ? [el("ul", { class: "issues" }, ...issueItems(chat.issues))]
      : [el("span", { class: "hint" }, "No problems found")]],
  ];
  if (chat.model) rows.push(["Model", [item(chat.model.name, chat.model.reason)]]);

  const list = el("dl", { class: "draft" });
  for (const [label, content] of rows) list.append(el("dt", {}, label), el("dd", {}, ...content.filter(Boolean)));

  const tag = errors.length ? "Has errors" : chat.ready ? "Draft · not run" : "Draft so far";
  return el("article", { class: "draft-card", "aria-label": "Drafted study" },
    el("div", { class: "draft-head" },
      el("div", {}, el("span", { class: "eyebrow" }, "Drafted study"), el("span", { class: "tag" }, tag)),
      firstQuestion ? el("h2", {}, firstQuestion.content) : null,
      el("p", {}, matchedOn
        ? `Compares ${options.exposureLabel(study.exposure)} members with similar patients who never enrolled, matched on ${matchedOn} characteristic${matchedOn === 1 ? "" : "s"}.`
        : `Compares ${options.exposureLabel(study.exposure)} members with patients who never enrolled, without matching.`)),
    list,
    el("div", { class: "draft-foot" },
      el("button", { type: "button", class: "primary", onclick: () => options.review(structuredClone(study)) }, "Review in builder"),
      el("button", { type: "button", onclick: () => $("chat-input").focus() }, "Ask for a change"),
      el("span", { class: "hint" }, errors.length
        ? "Answer the assistant, or fix the errors in the builder."
        : "Next: check the cohort, then covariates and outcome.")));
}
