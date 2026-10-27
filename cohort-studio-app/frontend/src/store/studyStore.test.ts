import { beforeEach, describe, expect, it, vi } from "vitest";

import { DRAFT, META, chatResult, fakeClient } from "../test/fixtures";
import type { FeatureSpec } from "../types";
import { STORAGE_KEY, resultsCurrent, useStudyStore } from "./studyStore";

const initial = useStudyStore.getState();

function store() {
  return useStudyStore.getState();
}

beforeEach(() => {
  localStorage.clear();
  useStudyStore.setState(initial, true);
  store().setMeta(META);
});

describe("manual changes", () => {
  it("update the study in the store and bump the revision", () => {
    const before = store().revision;
    store().setAgeRange(40, 65);
    store().setPersonFilter("gender", ["M"]);
    expect(store().study.age_min).toBe(40);
    expect(store().study.age_max).toBe(65);
    expect(store().study.person_filters).toEqual({ gender: ["M"] });
    expect(store().revision).toBe(before + 2);
    expect(store().lastChange).toBe("manual");
  });

  it("drop a filter when no value is left", () => {
    store().setPersonFilter("gender", ["F"]);
    store().setPersonFilter("gender", []);
    expect(store().study.person_filters).toEqual({});
  });

  it("keep one outcome: a new outcome replaces the old", () => {
    const outcome = DRAFT.features[0] as FeatureSpec;
    store().saveFeature(outcome, null);
    store().saveFeature({ ...outcome, name: "other", label: "Other" }, null);
    expect(store().study.features.map((f) => f.name)).toEqual(["other"]);
  });

  it("are saved so a refresh does not lose them", () => {
    store().setSeed(7);
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as { seed: number };
    expect(saved.seed).toBe(7);
  });
});

describe("assistant drafts", () => {
  it("are checked and then replace the study", () => {
    const result = store().applyAssistantDraft(DRAFT);
    expect(result.ok).toBe(true);
    expect(store().study).toEqual(DRAFT);
    expect(store().lastChange).toBe("assistant");
  });

  it("are refused when malformed or naming things the dataset lacks", () => {
    const before = store().study;
    expect(store().applyAssistantDraft({ ...DRAFT, exposure: "program_z" }).ok).toBe(false);
    expect(store().applyAssistantDraft({ ...DRAFT, age_min: "eighteen" }).ok).toBe(false);
    expect(store().applyAssistantDraft("not a study").ok).toBe(false);
    expect(store().study).toBe(before);
  });

  it("arrive through sendChat and update the store with no reload", async () => {
    const client = fakeClient();
    await store().sendChat("Does Programme A reduce ED visits?", client);
    expect(store().study.age_min).toBe(18);
    expect(store().study.person_filters).toEqual({ gender: ["F"] });
    expect(store().chat.hasDraft).toBe(true);
    expect(store().chat.ready).toBe(true);
    expect(store().chat.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
  });
});

describe("chat requests", () => {
  it("send no draft while the study is untouched", async () => {
    const client = fakeClient({ chat: vi.fn(() => Promise.resolve(chatResult({ draft: null }))) });
    await store().sendChat("Hello", client);
    expect(client.chat).toHaveBeenCalledWith({
      messages: [{ role: "user", content: "Hello" }],
      draft: null,
    });
  });

  it("carry the current study, manual edits included", async () => {
    const client = fakeClient();
    await store().sendChat("Draft it", client);
    // The user then changes the ages by hand...
    store().setAgeRange(50, null);
    await store().sendChat("Now restrict to women", client);
    const second = vi.mocked(client.chat).mock.calls[1]?.[0];
    expect(second?.draft?.age_min).toBe(50);
    expect(second?.draft?.age_max).toBeNull();
    expect(second?.messages.map((m) => m.role)).toEqual(["user", "assistant", "user"]);
  });

  it("take the message back when the request fails", async () => {
    const client = fakeClient({ chat: vi.fn(() => Promise.reject(new Error("offline"))) });
    await store().sendChat("Hello", client);
    expect(store().chat.messages).toEqual([]);
    expect(store().chat.error).toBe("offline");
    expect(store().chat.busy).toBe(false);
  });
});

describe("results", () => {
  it("go out of date when the study changes", async () => {
    store().applyAssistantDraft(DRAFT);
    const client = fakeClient({
      analysis: vi.fn(() => Promise.resolve({} as never)),
    });
    await store().runAnalysis(client);
    expect(resultsCurrent(store())).toBe(true);
    store().setSeed(3);
    expect(resultsCurrent(store())).toBe(false);
  });
});

describe("restoring", () => {
  it("brings back a saved study when the metadata loads", () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(DRAFT));
    useStudyStore.setState(initial, true);
    store().setMeta(META);
    expect(store().study).toEqual(DRAFT);
    expect(store().lastChange).toBe("restored");
  });
});
