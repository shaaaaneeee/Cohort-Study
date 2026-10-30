// The POC's look as an MUI theme: neutral greys, near-black primary buttons,
// a patina green for "ready", and the two group colours (blue = treated,
// orange = controls), which were checked for colour-blind separation and
// contrast in both light and dark.
import { createTheme } from "@mui/material/styles";

export const groupColors = {
  light: { treated: "#2563c9", control: "#e07b1a", before: "#9a9a9a" },
  dark: { treated: "#6b9cf0", control: "#f0a052", before: "#7a7a77" },
};

const sans = '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif';

export const theme = createTheme({
  cssVariables: { colorSchemeSelector: "data" },
  colorSchemes: {
    light: {
      palette: {
        primary: { main: "#111111", contrastText: "#ffffff" },
        secondary: { main: "#0f6e69" },
        success: { main: "#0f6e69" },
        error: { main: "#c0261f" },
        warning: { main: "#865700" },
        info: { main: "#2563c9" },
        background: { default: "#f5f5f5", paper: "#ffffff" },
        text: { primary: "#111111", secondary: "#5c5c5c" },
        divider: "rgba(0, 0, 0, 0.09)",
      },
    },
    dark: {
      palette: {
        primary: { main: "#f3f3f1", contrastText: "#111111" },
        secondary: { main: "#4fb3ac" },
        success: { main: "#4fb3ac" },
        error: { main: "#f0736b" },
        warning: { main: "#e3b14d" },
        info: { main: "#6b9cf0" },
        background: { default: "#0d0d0d", paper: "#1a1a19" },
        text: { primary: "#f3f3f1", secondary: "#a5a5a0" },
        divider: "rgba(255, 255, 255, 0.09)",
      },
    },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: sans,
    h1: { fontSize: "1.6rem", fontWeight: 650, letterSpacing: "-0.01em" },
    h2: { fontSize: "1.1rem", fontWeight: 650 },
    h3: { fontSize: "1rem", fontWeight: 650 },
    overline: { fontWeight: 650, letterSpacing: "0.08em", lineHeight: 1.6 },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiCard: {
      defaultProps: { variant: "outlined" },
      styleOverrides: {
        root: { boxShadow: "0 1px 1px rgba(0,0,0,0.04), 0 6px 16px rgba(0,0,0,0.06)" },
      },
    },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiSelect: { defaultProps: { size: "small" } },
    MuiAutocomplete: { defaultProps: { size: "small" } },
  },
});
