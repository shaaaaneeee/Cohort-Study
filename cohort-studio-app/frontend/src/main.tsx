import CssBaseline from "@mui/material/CssBaseline";
import { ThemeProvider } from "@mui/material/styles";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { api } from "./api/client";
import { ApiProvider } from "./api/context";
import { theme } from "./theme/theme";

const root = document.getElementById("root");
if (!root) throw new Error("No #root element");

createRoot(root).render(
  <StrictMode>
    <ThemeProvider theme={theme} defaultMode="system">
      <CssBaseline enableColorScheme />
      <ApiProvider client={api}>
        <App />
      </ApiProvider>
    </ThemeProvider>
  </StrictMode>,
);
