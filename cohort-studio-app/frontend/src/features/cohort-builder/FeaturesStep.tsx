import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormGroup from "@mui/material/FormGroup";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useStudyStore } from "../../store/studyStore";
import type { Role } from "../../types";
import { readable } from "../../utils/study";
import { FeatureList } from "./FeatureList";

interface Props {
  onAddFeature: (role: Role, index: number | null) => void;
}

/** Step 2: what to adjust for and what to measure. */
export function FeaturesStep({ onAddFeature }: Props) {
  const meta = useStudyStore((s) => s.meta);
  const study = useStudyStore((s) => s.study);
  const issues = useStudyStore((s) => s.check.issues);
  const setPersonCovariates = useStudyStore((s) => s.setPersonCovariates);
  const setStep = useStudyStore((s) => s.setStep);
  if (!meta) return null;

  const missingOutcome = !study.features.some((f) => f.role === "outcome");
  const errors = issues.some((i) => i.level === "error");
  const empty = study.features.length === 0;

  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h1">Covariates and outcome</Typography>
        <Typography color="text.secondary">
          Covariates describe patients before the index date; matching and the model adjust for
          them. The outcome is measured after it.
        </Typography>
      </Box>

      <Card>
        <CardHeader title="Person covariates" slotProps={{ title: { variant: "h2" } }} />
        <CardContent>
          <FormGroup row aria-label="Person covariates">
            {meta.person_covariates.map((c) => (
              <FormControlLabel
                key={c}
                label={readable(c)}
                control={
                  <Checkbox
                    checked={study.person_covariates.includes(c)}
                    onChange={(e) => {
                      const chosen = e.target.checked
                        ? meta.person_covariates.filter(
                            (x) => x === c || study.person_covariates.includes(x),
                          )
                        : study.person_covariates.filter((x) => x !== c);
                      setPersonCovariates(chosen);
                    }}
                  />
                }
              />
            ))}
          </FormGroup>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={`Covariates (${study.features.filter((f) => f.role === "covariate").length})`}
          slotProps={{ title: { variant: "h2" } }}
          action={
            <Button
              onClick={() => {
                onAddFeature("covariate", null);
              }}
            >
              + Add covariate
            </Button>
          }
        />
        <FeatureList
          role="covariate"
          empty="No covariates yet. Without any, the groups are compared without matching."
          onEdit={(index) => {
            onAddFeature("covariate", index);
          }}
        />
      </Card>

      <Card sx={{ borderColor: missingOutcome ? "warning.main" : undefined }}>
        <CardHeader
          title="Outcome"
          subheader="Exactly one"
          slotProps={{ title: { variant: "h2" } }}
        />
        {missingOutcome ? (
          <CardContent>
            <Alert
              severity="info"
              action={
                <Button
                  variant="contained"
                  onClick={() => {
                    onAddFeature("outcome", null);
                  }}
                >
                  Choose outcome
                </Button>
              }
            >
              The study needs an outcome before it can run.
            </Alert>
          </CardContent>
        ) : (
          <FeatureList
            role="outcome"
            empty={null}
            onEdit={(index) => {
              onAddFeature("outcome", index);
            }}
          />
        )}
      </Card>

      <Stack
        direction="row"
        spacing={1}
        sx={{ justifyContent: "space-between", alignItems: "center" }}
      >
        <Button
          onClick={() => {
            setStep("cohort");
          }}
        >
          ← Back to Cohort
        </Button>
        <Typography variant="body2" color="text.secondary">
          {errors
            ? "Next: fix the design check, then Run analysis →"
            : empty
              ? ""
              : "Next: Run analysis, in the sidebar →"}
        </Typography>
      </Stack>
    </Stack>
  );
}
