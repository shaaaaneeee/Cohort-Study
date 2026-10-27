import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";

import type { Issue } from "../types";

interface Props {
  issues: Issue[];
  /** Turns a feature name into its label, to say which feature an issue belongs to. */
  labelFor?: (feature: string) => string;
  /** An optional button per issue, such as "Fix in Cohort". */
  action?: (issue: Issue) => { label: string; onClick: () => void } | null;
}

/** One alert per issue, with its level written out so it never depends on colour. */
export function IssueList({ issues, labelFor, action }: Props) {
  if (!issues.length) return null;
  return (
    <Stack spacing={0.75} component="ul" sx={{ p: 0, m: 0, listStyle: "none" }} aria-live="polite">
      {issues.map((issue, i) => {
        const button = action?.(issue) ?? null;
        const prefix = labelFor && issue.feature ? `${labelFor(issue.feature)}: ` : "";
        return (
          <Alert
            key={`${issue.code}-${issue.feature ?? ""}-${i}`}
            component="li"
            severity={issue.level === "error" ? "error" : "warning"}
            variant="outlined"
            sx={{ py: 0, alignItems: "center" }}
            action={
              button ? (
                <Button size="small" color="inherit" onClick={button.onClick}>
                  {button.label}
                </Button>
              ) : undefined
            }
          >
            <strong>{issue.level === "error" ? "Error" : "Warning"}</strong> · {prefix}
            {issue.message}
          </Alert>
        );
      })}
    </Stack>
  );
}
