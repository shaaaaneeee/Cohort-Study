import Box from "@mui/material/Box";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import Typography from "@mui/material/Typography";

import { resultsCurrent, useStudyStore } from "../store/studyStore";
import type { StepName } from "../types";
import { formatCount, plural, timeOfDay } from "../utils/format";

const STEPS: { name: StepName; label: string }[] = [
  { name: "ask", label: "Ask" },
  { name: "cohort", label: "Cohort" },
  { name: "features", label: "Covariates and outcome" },
  { name: "results", label: "Results" },
];

/** The step bar: one tab per step, with a line saying where each stands. */
export function StepTabs() {
  const state = useStudyStore();
  const { study, check, attrition, run, chat, step, setStep } = state;
  const errors = check.issues.filter((i) => i.level === "error").length;
  const empty = study.features.length === 0;
  const outcomes = study.features.filter((f) => f.role === "outcome").length;
  const adjustments =
    study.person_covariates.length + study.features.filter((f) => f.role === "covariate").length;
  const last = attrition.result?.steps.at(-1);
  const current = resultsCurrent(state);

  const subs: Record<StepName, string> = {
    ask: chat.hasDraft ? "Draft ready" : "Describe your study",
    cohort: last
      ? `${formatCount(last.treated)} treated · ${formatCount(last.control)} controls`
      : "Counting…",
    features: empty
      ? "Nothing added yet"
      : errors
        ? `${plural(errors, "error")} to fix`
        : `${plural(adjustments, "adjustment")} · ${plural(outcomes, "outcome")}`,
    results:
      run.at === null ? "Not run yet" : current ? `Run at ${timeOfDay(run.at)}` : "Out of date",
  };

  return (
    <Box sx={{ borderBottom: 1, borderColor: "divider", bgcolor: "background.paper" }}>
      <Tabs
        value={step}
        onChange={(_, value: StepName) => {
          setStep(value);
        }}
        variant="scrollable"
        allowScrollButtonsMobile
        aria-label="Study steps"
      >
        {STEPS.map((s, i) => (
          <Tab
            key={s.name}
            value={s.name}
            id={`tab-${s.name}`}
            aria-controls={`panel-${s.name}`}
            sx={{ alignItems: "flex-start", textAlign: "left" }}
            label={
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 650 }}>
                  {i}. {s.label}
                </Typography>
                <Typography
                  variant="caption"
                  color={s.name === "features" && errors && !empty ? "error" : "text.secondary"}
                >
                  {subs[s.name]}
                </Typography>
              </Box>
            }
          />
        ))}
      </Tabs>
    </Box>
  );
}
