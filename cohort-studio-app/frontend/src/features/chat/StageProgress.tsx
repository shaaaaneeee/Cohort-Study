import Step from "@mui/material/Step";
import StepLabel from "@mui/material/StepLabel";
import Stepper from "@mui/material/Stepper";

import type { ChatStage } from "../../types";

/** The assistant's stages, S0 to S4, with the current one highlighted. */
const TITLES = ["Question", "Cohort", "Covariates", "Outcome", "Review"];

export function StageProgress({ stage, ready }: { stage: ChatStage; ready: boolean }) {
  const titles =
    stage.total === TITLES.length ? TITLES : Array.from({ length: stage.total }, (_, i) => `S${i}`);
  return (
    <Stepper
      activeStep={ready ? stage.total : stage.number}
      alternativeLabel
      aria-label={`Step ${stage.number + 1} of ${stage.total}: ${stage.title}`}
      sx={{ mb: 2, "& .MuiStepLabel-label": { fontSize: "0.75rem" } }}
    >
      {titles.map((title, i) => (
        <Step key={title} completed={ready || i < stage.number}>
          <StepLabel>{i === stage.number ? stage.title : title}</StepLabel>
        </Step>
      ))}
    </Stepper>
  );
}
