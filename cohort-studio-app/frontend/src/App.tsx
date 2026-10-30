import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Container from "@mui/material/Container";
import Grid from "@mui/material/Grid";
import { useCallback, useEffect, useState } from "react";

import { useApi } from "./api/context";
import { AppHeader } from "./components/AppHeader";
import { Sidebar } from "./components/Sidebar";
import { StepTabs } from "./components/StepTabs";
import { ChatPanel } from "./features/chat/ChatPanel";
import { CohortStep } from "./features/cohort-builder/CohortStep";
import { FeatureDialog, type Editing } from "./features/cohort-builder/FeatureDialog";
import { FeaturesStep } from "./features/cohort-builder/FeaturesStep";
import { ResultsStep } from "./features/results/ResultsStep";
import { useStudyCheck } from "./hooks/useStudyCheck";
import { useStudyStore } from "./store/studyStore";

export function App() {
  const client = useApi();
  const meta = useStudyStore((s) => s.meta);
  const step = useStudyStore((s) => s.step);
  const setMeta = useStudyStore((s) => s.setMeta);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);

  const load = useCallback(() => {
    client.metadata().then(
      (meta) => {
        setLoadError(null);
        setMeta(meta);
      },
      (error: unknown) => {
        setLoadError(error instanceof Error ? error.message : String(error));
      },
    );
  }, [client, setMeta]);

  useEffect(load, [load]);
  useStudyCheck(client);

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppHeader />
      {loadError && (
        <Alert
          severity="error"
          role="alert"
          action={
            <Button color="inherit" onClick={load}>
              Try again
            </Button>
          }
        >
          Could not load the dataset description: {loadError}
        </Alert>
      )}
      {!meta && !loadError && (
        <Box sx={{ display: "flex", justifyContent: "center", p: 6 }}>
          <CircularProgress aria-label="Loading" />
        </Box>
      )}
      {meta && (
        <>
          <StepTabs />
          <Container maxWidth="xl" sx={{ py: 3 }}>
            <Grid container spacing={3}>
              <Grid size={{ xs: 12, md: 8, lg: 9 }}>
                <Box role="tabpanel" id={`panel-${step}`} aria-labelledby={`tab-${step}`}>
                  {step === "ask" && <ChatPanel />}
                  {step === "cohort" && (
                    <CohortStep
                      onAddFeature={(index) => {
                        setEditing({ role: "inclusion", index });
                      }}
                    />
                  )}
                  {step === "features" && (
                    <FeaturesStep
                      onAddFeature={(role, index) => {
                        setEditing({ role, index });
                      }}
                    />
                  )}
                  {step === "results" && <ResultsStep />}
                </Box>
              </Grid>
              <Grid size={{ xs: 12, md: 4, lg: 3 }}>
                <Sidebar />
              </Grid>
            </Grid>
          </Container>
          {editing && (
            <FeatureDialog
              key={`${editing.role}-${editing.index ?? "new"}`}
              editing={editing}
              onClose={() => {
                setEditing(null);
              }}
            />
          )}
        </>
      )}
    </Box>
  );
}
