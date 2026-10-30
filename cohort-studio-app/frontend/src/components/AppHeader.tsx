import DarkModeOutlined from "@mui/icons-material/DarkModeOutlined";
import LightModeOutlined from "@mui/icons-material/LightModeOutlined";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import { useColorScheme } from "@mui/material/styles";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import { useStudyStore } from "../store/studyStore";
import { checkDraft } from "../utils/study";
import { ConfirmDialog } from "./ConfirmDialog";

export function AppHeader() {
  const meta = useStudyStore((s) => s.meta);
  const study = useStudyStore((s) => s.study);
  const newStudy = useStudyStore((s) => s.newStudy);
  const replaceStudy = useStudyStore((s) => s.replaceStudy);
  const setStep = useStudyStore((s) => s.setStep);
  const { mode, systemMode, setMode } = useColorScheme();
  const [confirmNew, setConfirmNew] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const dark = (mode === "system" ? systemMode : mode) === "dark";

  function saveFile() {
    const blob = new Blob([JSON.stringify(study, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "study.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function openFile(file: File) {
    try {
      const parsed: unknown = JSON.parse(await file.text());
      const checked = checkDraft(parsed, meta);
      if (!checked.ok) {
        setNotice(`${file.name} is not a study file: ${checked.problems.join(" ")}`);
        return;
      }
      replaceStudy(checked.study, "file");
      setStep("cohort");
    } catch {
      setNotice(`${file.name} is not a study file.`);
    }
  }

  return (
    <AppBar
      position="static"
      color="inherit"
      elevation={0}
      sx={{ borderBottom: 1, borderColor: "divider" }}
    >
      <Toolbar sx={{ gap: 2, flexWrap: "wrap" }}>
        <Typography variant="h1" component="div" sx={{ fontSize: "1.15rem" }}>
          cohort-studio
        </Typography>
        <Box sx={{ display: "flex", flexDirection: "column" }}>
          <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1 }}>
            Dataset
          </Typography>
          <Typography variant="body2">{meta?.dataset ?? "…"}</Typography>
        </Box>
        <Box sx={{ flexGrow: 1 }} />
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <Tooltip title={dark ? "Light theme" : "Dark theme"}>
            <IconButton
              aria-label={dark ? "Use the light theme" : "Use the dark theme"}
              onClick={() => {
                setMode(dark ? "light" : "dark");
              }}
            >
              {dark ? <LightModeOutlined /> : <DarkModeOutlined />}
            </IconButton>
          </Tooltip>
          <Button
            variant="outlined"
            onClick={() => {
              setConfirmNew(true);
            }}
          >
            New study
          </Button>
          <Button variant="outlined" component="label">
            Open study file
            <input
              hidden
              type="file"
              accept=".json,application/json"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void openFile(file);
              }}
            />
          </Button>
          <Button variant="outlined" onClick={saveFile}>
            Save study file
          </Button>
        </Stack>
      </Toolbar>
      <ConfirmDialog
        open={confirmNew}
        title="Start a new study?"
        message="The study in the builder and the conversation will be cleared."
        confirmLabel="New study"
        onConfirm={newStudy}
        onClose={() => {
          setConfirmNew(false);
        }}
      />
      <Snackbar
        open={notice !== null}
        autoHideDuration={6000}
        message={notice}
        onClose={() => {
          setNotice(null);
        }}
      />
    </AppBar>
  );
}
