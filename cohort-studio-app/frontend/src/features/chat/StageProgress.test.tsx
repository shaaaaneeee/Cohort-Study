import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StageProgress } from "./StageProgress";

describe("StageProgress", () => {
  it("shows every stage and marks the current one", () => {
    render(
      <StageProgress
        stage={{ id: "outcome", number: 3, title: "Outcome", total: 5 }}
        ready={false}
      />,
    );
    for (const title of ["Question", "Cohort", "Covariates", "Outcome", "Review"]) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    expect(screen.getByLabelText("Step 4 of 5: Outcome")).toBeTruthy();
  });
});
