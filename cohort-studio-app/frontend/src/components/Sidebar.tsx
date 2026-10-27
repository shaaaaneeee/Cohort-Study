import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useApi } from "../api/context";
import { resultsCurrent, useStudyStore } from "../store/studyStore";
import type { Issue, StepName } from "../types";
import { formatCount, plural, timeOfDay } from "../utils/format";
import { IssueList } from "./IssueList";

/** The design check, the cohort size and the model. It decides whether the study can run. */
export function Sidebar() {
  const client = useApi();
  const state = useStudyStore();
  const { study, check, attrition, run, setStep, runAnalysis } = state;
  const errors = check.issues.filter((i) => i.level === "error").length;
  const warnings = check.issues.length - errors;
  const empty = study.features.length === 0;
  const current = resultsCurrent(state);

  let tone: "empty" | "errors" | "ran" | "ready";
  let title: string;
  let sub: string;
  let foot: string;
  if (empty) {
    tone = "empty";
    title = "No study yet";
    sub = "Ask a question, open a study file, or add features in steps 1 and 2.";
    foot = "Run analysis turns on once a study is drafted and passes the check.";
  } else if (errors) {
    tone = "errors";
    title = `${plural(errors, "error")} ${errors === 1 ? "blocks" : "block"} running`;
    sub = "Fix these, then run.";
    foot = "Run analysis is off until the errors are fixed. Warnings do not block it.";
  } else if (current && run.at) {
    tone = "ran";
    title = "Results are up to date";
    sub = `Run at ${timeOfDay(run.at)}${warnings ? ` · ${plural(warnings, "warning")}` : ""}`;
    foot = "Change anything in steps 1 or 2 and these results go out of date.";
  } else {
    tone = "ready";
    title = "Ready to run";
    sub = `No errors${warnings ? ` · ${plural(warnings, "warning")}` : ""}`;
    foot = "The assistant only drafts. Nothing runs until you press Run analysis.";
  }
  const border = {
    empty: "divider",
    errors: "error.main",
    ran: "success.main",
    ready: "success.main",
  }[tone];

  // The step where an issue can be fixed, from the role of its feature.
  function fixIn(issue: Issue): { label: string; onClick: () => void } {
    const feature = issue.feature
      ? study.features.find((f) => f.name === issue.feature)
      : undefined;
    let target: StepName = "cohort";
    let label = "Review in Cohort";
    if (feature?.role === "inclusion") label = "Fix in Cohort";
    else if (feature || issue.code === "outcome_count") {
      target = "features";
      label = "Fix in Covariates and outcome";
    }
    return {
      label,
      onClick: () => {
        setStep(target);
      },
    };
  }

  const labelFor = (name: string) => study.features.find((f) => f.name === name)?.label ?? name;
  const last = attrition.result?.steps.at(-1);
  const small = attrition.result?.issues.filter((i) => i.code === "small_cell").length ?? 0;

  return (
    <Stack spacing={2} component="aside" aria-label="Design check">
      <Card sx={{ borderColor: border, borderWidth: tone === "empty" ? 1 : 2 }}>
        <CardContent>
          <Typography variant="h2" id="check-title">
            {title}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            {sub}
          </Typography>
          {!empty && <IssueList issues={check.issues} labelFor={labelFor} action={fixIn} />}
          <Button
            fullWidth
            variant="contained"
            sx={{ mt: 2 }}
            disabled={empty || errors > 0 || run.running}
            onClick={() => {
              void runAnalysis(client);
            }}
          >
            {run.running ? "Running…" : current ? "Run again" : "Run analysis"}
          </Button>
          <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 1 }}>
            {foot}
          </Typography>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">
            Cohort
          </Typography>
          <Stack direction="row" spacing={2}>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Treated
              </Typography>
              <Typography variant="h2" data-testid="count-treated">
                {formatCount(last?.treated)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                Controls
              </Typography>
              <Typography variant="h2" data-testid="count-control">
                {formatCount(last?.control)}
              </Typography>
            </Box>
          </Stack>
          <Typography variant="caption" color="text.secondary" aria-live="polite">
            {attrition.error
              ? attrition.error.designErrors
                ? "Counts appear once the design errors are fixed."
                : `Counts are not available: ${attrition.error.message}`
              : small
                ? "Some counts are below 5; see the table in step 1."
                : "After every eligibility step."}
          </Typography>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="overline" color="text.secondary">
            Model
          </Typography>
          <Typography variant="body1" sx={{ fontWeight: 600 }}>
            {check.model?.name ?? "Not set yet"}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {check.model?.reason ?? "Chosen from the outcome once it is set."}
          </Typography>
        </CardContent>
      </Card>
    </Stack>
  );
}
