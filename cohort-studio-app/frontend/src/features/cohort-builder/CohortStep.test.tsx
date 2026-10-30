import { ThemeProvider } from "@mui/material/styles";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiProvider } from "../../api/context";
import { useStudyStore } from "../../store/studyStore";
import { DRAFT, META, fakeClient } from "../../test/fixtures";
import { theme } from "../../theme/theme";
import { CohortStep } from "./CohortStep";

const initial = useStudyStore.getState();

function renderStep() {
  return render(
    <ThemeProvider theme={theme}>
      <ApiProvider client={fakeClient()}>
        <CohortStep onAddFeature={() => undefined} />
      </ApiProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useStudyStore.setState(initial, true);
  useStudyStore.getState().setMeta(META);
});

describe("the cohort controls", () => {
  it("update live when the assistant's draft is applied", async () => {
    renderStep();
    const youngest = screen.getByLabelText<HTMLInputElement>("Youngest age");
    expect(youngest.value).toBe("");

    act(() => {
      useStudyStore.getState().applyAssistantDraft(DRAFT);
    });

    expect(screen.getByLabelText<HTMLInputElement>("Youngest age").value).toBe("18");
    expect(screen.getByLabelText<HTMLInputElement>("Oldest age").value).toBe("80");
    // The gender filter shows the drafted value as a chip.
    const gender = screen.getByLabelText("Gender").closest(".MuiAutocomplete-root");
    expect(gender).not.toBeNull();
    expect(await within(gender as HTMLElement).findByText("F")).toBeInTheDocument();
  });

  it("write manual changes to the store", async () => {
    renderStep();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Youngest age"), "45");
    expect(useStudyStore.getState().study.age_min).toBe(45);
    await user.clear(screen.getByLabelText("Youngest age"));
    expect(useStudyStore.getState().study.age_min).toBeNull();
  });
});
