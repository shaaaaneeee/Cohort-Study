// The one store for the study being built.
//
// `study` is a StudySpec exactly as the backend defines it. The cohort
// builder and the chat both read and write it here and nowhere else:
//   - a manual change (exposure, ages, filters, features) updates `study`;
//   - every chat request sends the current `study` as the draft, so the
//     assistant refines what the user sees, manual edits included;
//   - a study the assistant proposes is checked (checkDraft) and then
//     replaces `study`, and every control re-renders from it at once.
import { create } from "zustand";

import type { ApiClient } from "../api/client";
import { ApiError } from "../api/client";
import type {
  AnalysisResult,
  AttritionResult,
  ChatResult,
  FeatureSpec,
  ImpliedModel,
  Issue,
  Metadata,
  StepName,
  StudySpec,
} from "../types";
import { checkDraft, emptyStudy, isBlankStudy, normaliseStudy } from "../utils/study";

export const STORAGE_KEY = "cohort-studio:study";

export type ChangeSource = "manual" | "assistant" | "file" | "new" | "restored";

export interface ChatEntry {
  role: "user" | "assistant";
  /** What /api/chat gets back as history. */
  content: string;
  status?: ChatResult["status"];
  reply?: string;
  questions?: string[];
}

export interface ChatState {
  messages: ChatEntry[];
  busy: boolean;
  error: string | null;
  /** Issues and model of the assistant's last draft, for the draft card. */
  draftIssues: Issue[];
  draftModel: ImpliedModel | null;
  hasDraft: boolean;
  ready: boolean;
}

export interface CheckState {
  issues: Issue[];
  model: ImpliedModel | null;
}

export interface AttritionState {
  result: AttritionResult | null;
  /** Why the counts are missing, when they are. */
  error: { message: string; designErrors: boolean } | null;
}

export interface RunState {
  result: AnalysisResult | null;
  /** The study (as JSON) the result on screen was computed from. */
  studyJson: string | null;
  at: Date | null;
  running: boolean;
  error: ApiError | null;
}

export interface StudyStore {
  meta: Metadata | null;
  study: StudySpec;
  /** Increases with every change to `study`. */
  revision: number;
  lastChange: ChangeSource;
  step: StepName;
  check: CheckState;
  attrition: AttritionState;
  run: RunState;
  chat: ChatState;

  setMeta: (meta: Metadata) => void;
  setStep: (step: StepName) => void;
  replaceStudy: (study: Partial<StudySpec>, source: ChangeSource) => void;
  newStudy: () => void;
  setExposure: (exposure: string) => void;
  setSeed: (seed: number) => void;
  setAgeRange: (ageMin: number | null, ageMax: number | null) => void;
  setPersonFilter: (attribute: string, values: string[]) => void;
  setPersonCovariates: (covariates: string[]) => void;
  saveFeature: (feature: FeatureSpec, index: number | null) => void;
  removeFeature: (index: number) => void;
  applyAssistantDraft: (draft: unknown) => { ok: boolean; problems: string[] };
  setCheck: (check: CheckState) => void;
  setAttrition: (attrition: AttritionState) => void;
  sendChat: (text: string, client: ApiClient) => Promise<void>;
  resetChat: () => void;
  runAnalysis: (client: ApiClient) => Promise<void>;
}

const emptyChat: ChatState = {
  messages: [],
  busy: false,
  error: null,
  draftIssues: [],
  draftModel: null,
  hasDraft: false,
  ready: false,
};

const emptyRun: RunState = { result: null, studyJson: null, at: null, running: false, error: null };

export function loadSavedStudy(): Partial<StudySpec> | null {
  // Kept in this browser only, so a refresh does not lose work. Some
  // browsers refuse storage (private windows); there is then no draft.
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? (JSON.parse(saved) as Partial<StudySpec>) : null;
  } catch {
    return null;
  }
}

function saveStudy(study: StudySpec): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(study));
  } catch {
    // Nothing to do: the draft is simply not kept.
  }
}

export const useStudyStore = create<StudyStore>()((set, get) => {
  /** Every change to the study goes through here. */
  function commit(study: StudySpec, source: ChangeSource): void {
    saveStudy(study);
    set((s) => ({ study, revision: s.revision + 1, lastChange: source }));
  }

  function change(recipe: (study: StudySpec) => StudySpec): void {
    commit(recipe(get().study), "manual");
  }

  return {
    meta: null,
    study: emptyStudy(null),
    revision: 0,
    lastChange: "new",
    step: "ask",
    check: { issues: [], model: null },
    attrition: { result: null, error: null },
    run: emptyRun,
    chat: emptyChat,

    setMeta(meta) {
      const saved = loadSavedStudy();
      const study = normaliseStudy(saved ?? {}, meta);
      if (!study.exposure || !meta.exposures.some((x) => x.name === study.exposure)) {
        study.exposure = meta.exposures[0]?.name ?? "";
      }
      set((s) => ({
        meta,
        study,
        revision: s.revision + 1,
        lastChange: saved ? "restored" : "new",
        step: saved && study.features.length ? "cohort" : s.step,
      }));
    },

    setStep(step) {
      set({ step });
    },

    replaceStudy(study, source) {
      commit(normaliseStudy(study, get().meta), source);
    },

    newStudy() {
      commit(emptyStudy(get().meta), "new");
      set({ run: emptyRun, chat: emptyChat, step: "ask" });
    },

    setExposure(exposure) {
      change((s) => ({ ...s, exposure }));
    },

    setSeed(seed) {
      change((s) => ({ ...s, seed: Math.max(0, Math.trunc(seed) || 0) }));
    },

    setAgeRange(ageMin, ageMax) {
      change((s) => ({ ...s, age_min: ageMin, age_max: ageMax }));
    },

    setPersonFilter(attribute, values) {
      change((s) => {
        const filters = Object.fromEntries(
          Object.entries(s.person_filters).filter(([key]) => key !== attribute),
        );
        if (values.length) filters[attribute] = [...values];
        return { ...s, person_filters: filters };
      });
    },

    setPersonCovariates(covariates) {
      change((s) => ({ ...s, person_covariates: [...covariates] }));
    },

    saveFeature(feature, index) {
      change((s) => {
        let features = [...s.features];
        if (index !== null) {
          features[index] = feature;
        } else {
          // One outcome per study: a new one replaces the old.
          if (feature.role === "outcome") features = features.filter((f) => f.role !== "outcome");
          features.push(feature);
        }
        return { ...s, features };
      });
    },

    removeFeature(index) {
      change((s) => ({ ...s, features: s.features.filter((_, i) => i !== index) }));
    },

    applyAssistantDraft(draft) {
      const checked = checkDraft(draft, get().meta);
      if (!checked.ok) return { ok: false, problems: checked.problems };
      if (JSON.stringify(checked.study) !== JSON.stringify(get().study)) {
        commit(checked.study, "assistant");
      }
      return { ok: true, problems: [] };
    },

    setCheck(check) {
      set({ check });
    },

    setAttrition(attrition) {
      set({ attrition });
    },

    async sendChat(text, client) {
      const content = text.trim();
      const { chat, study, meta } = get();
      if (!content || chat.busy) return;
      const messages: ChatEntry[] = [...chat.messages, { role: "user", content }];
      set({ chat: { ...chat, messages, busy: true, error: null } });
      try {
        // The study in the builder, manual edits included, goes with every
        // turn. An untouched study is not sent, so a first question starts
        // from scratch rather than "refining" an empty study.
        const result = await client.chat({
          messages: messages.map(({ role, content: c }) => ({ role, content: c })),
          draft: isBlankStudy(study, meta) ? null : study,
        });
        let reply = result.reply;
        if (result.questions.length) {
          reply += "\n\n" + result.questions.map((q, i) => `${i + 1}. ${q}`).join("\n");
        }
        const entry: ChatEntry = {
          role: "assistant",
          content: reply,
          status: result.status,
          reply: result.reply,
          questions: result.questions,
        };
        let next: ChatState = { ...get().chat, messages: [...messages, entry], busy: false };
        if (result.draft) {
          const applied = get().applyAssistantDraft(result.draft);
          next = {
            ...next,
            hasDraft: applied.ok,
            draftIssues: result.issues,
            draftModel: result.model,
            ready: applied.ok && result.status === "ready",
            error: applied.ok
              ? null
              : `The drafted study was not applied: ${applied.problems.join(" ")}`,
          };
        }
        set({ chat: next });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        // The message is taken back so it can be sent again.
        set({ chat: { ...get().chat, messages: chat.messages, busy: false, error: message } });
      }
    },

    resetChat() {
      set({ chat: emptyChat });
    },

    async runAnalysis(client) {
      const study = get().study;
      set((s) => ({ run: { ...s.run, running: true, error: null }, step: "results" }));
      try {
        const result = await client.analysis(study);
        set({
          run: {
            result,
            studyJson: JSON.stringify(study),
            at: new Date(),
            running: false,
            error: null,
          },
        });
      } catch (error) {
        const apiError = error instanceof ApiError ? error : new ApiError(String(error), 0);
        set((s) => ({ run: { ...s.run, running: false, error: apiError } }));
      }
    },
  };
});

/** Whether the result on screen came from the study as it is now. */
export function resultsCurrent(state: Pick<StudyStore, "run" | "study">): boolean {
  return state.run.studyJson !== null && state.run.studyJson === JSON.stringify(state.study);
}
