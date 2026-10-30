import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActions from "@mui/material/CardActions";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

import { IssueList } from "../../components/IssueList";
import { useStudyStore } from "../../store/studyStore";
import type { Role } from "../../types";
import { describe, readable } from "../../utils/study";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { sm: "160px 1fr" }, gap: 1, py: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>
        {label}
      </Typography>
      <Box>{children}</Box>
    </Box>
  );
}

/**
 * The study as it stands in the store, summarised. It is already in the
 * builder: the assistant's draft was applied when it arrived, and any manual
 * change shows here too.
 */
export function DraftCard({ onAskChange }: { onAskChange: () => void }) {
  const meta = useStudyStore((s) => s.meta);
  const study = useStudyStore((s) => s.study);
  const chat = useStudyStore((s) => s.chat);
  const setStep = useStudyStore((s) => s.setStep);

  const exposureLabel =
    meta?.exposures.find((x) => x.name === study.exposure)?.label ?? study.exposure;
  const errors = chat.draftIssues.filter((i) => i.level === "error");
  const covariates = study.features.filter((f) => f.role === "covariate");
  const matchedOn = study.person_covariates.length + covariates.length;
  const question = chat.messages.find((m) => m.role === "user")?.content;
  const people: string[] = [];
  if (study.age_min != null || study.age_max != null) {
    people.push(`aged ${study.age_min ?? 0} to ${study.age_max ?? "any"}`);
  }
  for (const [attribute, values] of Object.entries(study.person_filters)) {
    people.push(`${readable(attribute)}: ${values.join(", ")}`);
  }
  const byRole = (role: Role) =>
    study.features
      .filter((f) => f.role === role)
      .map((f) => (
        <Box key={f.name} sx={{ mb: 0.5 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {f.label}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {describe(f, meta)}
          </Typography>
        </Box>
      ));
  const none = (text: string) => (
    <Typography variant="body2" color="text.secondary">
      {text}
    </Typography>
  );
  const tag = errors.length ? "Has errors" : chat.ready ? "Draft · not run" : "Draft so far";

  return (
    <Card aria-label="Drafted study">
      <CardContent>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 1 }}>
          <Typography variant="overline" color="text.secondary">
            Drafted study
          </Typography>
          <Chip size="small" label={tag} color={errors.length ? "error" : "default"} />
        </Stack>
        {question && (
          <Typography variant="h2" sx={{ mb: 1 }}>
            {question}
          </Typography>
        )}
        <Typography variant="body2" sx={{ mb: 1 }}>
          {matchedOn
            ? `Compares ${exposureLabel} members with similar patients who never enrolled, matched on ${matchedOn} characteristic${matchedOn === 1 ? "" : "s"}.`
            : `Compares ${exposureLabel} members with patients who never enrolled, without matching.`}
        </Typography>
        <Divider />
        <Row label="Treatment group">
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {exposureLabel}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Index date: enrolment date · controls never enrolled
            {people.length ? ` · ${people.join(" · ")}` : ""}
          </Typography>
        </Row>
        <Row label="Inclusion criteria">
          {byRole("inclusion").length ? byRole("inclusion") : none("None: everyone is eligible")}
        </Row>
        <Row label="Adjusted for">
          <Stack direction="row" spacing={0.5} sx={{ flexWrap: "wrap", rowGap: 0.5, mb: 0.5 }}>
            {study.person_covariates.map((c) => (
              <Chip key={c} size="small" label={readable(c)} />
            ))}
          </Stack>
          {byRole("covariate")}
        </Row>
        <Row label="Outcome">
          {byRole("outcome").length ? byRole("outcome") : none("Not chosen yet")}
        </Row>
        <Row label="Design check">
          {chat.draftIssues.length ? (
            <IssueList issues={chat.draftIssues} />
          ) : (
            none("No problems found")
          )}
        </Row>
        {chat.draftModel && (
          <Row label="Model">
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              {chat.draftModel.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {chat.draftModel.reason}
            </Typography>
          </Row>
        )}
      </CardContent>
      <CardActions sx={{ px: 2, pb: 2, flexWrap: "wrap", gap: 1 }}>
        <Button
          variant="contained"
          onClick={() => {
            setStep("cohort");
          }}
        >
          Review in builder
        </Button>
        <Button variant="outlined" onClick={onAskChange}>
          Ask for a change
        </Button>
        <Typography variant="caption" color="text.secondary">
          {errors.length
            ? "Answer the assistant, or fix the errors in the builder."
            : "The builder already shows this study. Next: check the cohort, then covariates and outcome."}
        </Typography>
      </CardActions>
    </Card>
  );
}
