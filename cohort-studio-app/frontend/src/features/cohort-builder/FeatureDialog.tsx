import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormHelperText from "@mui/material/FormHelperText";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import { ApiError } from "../../api/client";
import { useApi } from "../../api/context";
import { IssueList } from "../../components/IssueList";
import { ValueMultiSelect } from "../../components/ValueMultiSelect";
import { useStudyStore } from "../../store/studyStore";
import type { Aggregation, FeatureSpec, Issue, PreviewResult, Role } from "../../types";
import { formatCount, formatNumber } from "../../utils/format";
import {
  AGGREGATION_LABELS,
  aggregationsFor,
  defaultFeature,
  MEASURE_AGGREGATIONS,
  nameFor,
  OPERATORS,
  presetsFor,
  ROLE_NAMES,
  sourceOf,
  unitsFor,
} from "../../utils/study";

export interface Editing {
  role: Role;
  index: number | null;
}

interface Props {
  editing: Editing;
  onClose: () => void;
}

type Grain = NonNullable<FeatureSpec["periodise"]>["grain"];

/** Add or edit one covariate, outcome or inclusion criterion. */
export function FeatureDialog({ editing, onClose }: Props) {
  const client = useApi();
  const meta = useStudyStore((s) => s.meta);
  const study = useStudyStore((s) => s.study);
  const saveFeature = useStudyStore((s) => s.saveFeature);
  if (!meta) throw new Error("FeatureDialog needs the metadata");

  const existing = editing.index === null ? null : (study.features[editing.index] ?? null);
  const [f, setF] = useState<FeatureSpec>(() =>
    existing ? structuredClone(existing) : defaultFeature(editing.role, meta),
  );
  const [periodise, setPeriodise] = useState(Boolean(f.periodise));
  const [grain, setGrain] = useState<Grain>(f.periodise?.grain ?? "quarter");
  const [periods, setPeriods] = useState<string>(String(f.periodise?.n ?? 4));
  const [from, setFrom] = useState(String(f.window.from));
  const [to, setTo] = useState(String(f.window.to));
  const [preview, setPreview] = useState<
    | { state: "idle" }
    | { state: "busy" }
    | { state: "done"; result: PreviewResult }
    | { state: "error"; message: string; issues: Issue[] }
  >({ state: "idle" });
  const [labelError, setLabelError] = useState(false);

  const role = editing.role;
  const source = sourceOf(meta, f.source) ?? meta.sources[0];
  if (!source) throw new Error("The dataset has no sources");
  const units = unitsFor(source, meta);
  const allowed = aggregationsFor(role, source, meta);
  const measures = source.measures.filter((m) => m.aggregations.includes(f.aggregation));
  const needsMeasure = MEASURE_AGGREGATIONS.includes(f.aggregation);
  const canPeriodise = role !== "inclusion" && f.aggregation !== "time_to_first";
  const name = nameFor(f.label, study, meta, editing.index);

  function changeSource(next: string) {
    const s = sourceOf(meta, next);
    if (!s || !meta) return;
    const nextUnits = unitsFor(s, meta);
    const nextAllowed = aggregationsFor(role, s, meta);
    const aggregation = nextAllowed.includes(f.aggregation)
      ? f.aggregation
      : (nextAllowed[0] ?? "count");
    setF({
      ...f,
      source: next,
      filters: {},
      aggregation,
      measure: MEASURE_AGGREGATIONS.includes(aggregation)
        ? (s.measures.find((m) => m.aggregations.includes(aggregation))?.name ?? null)
        : null,
      window: {
        ...f.window,
        unit: nextUnits.includes(f.window.unit) ? f.window.unit : (nextUnits[0] ?? "years"),
      },
    });
  }

  function changeAggregation(aggregation: Aggregation) {
    const measure = MEASURE_AGGREGATIONS.includes(aggregation)
      ? (source?.measures.find((m) => m.aggregations.includes(aggregation))?.name ?? null)
      : null;
    setF({ ...f, aggregation, measure });
  }

  function read(): FeatureSpec {
    const feature: FeatureSpec = {
      name,
      label: f.label.trim(),
      source: f.source,
      filters: f.filters,
      window: {
        anchor: "index",
        from: Number.parseInt(from, 10),
        to: Number.parseInt(to, 10),
        unit: f.window.unit,
      },
      aggregation: f.aggregation,
      role,
    };
    if (needsMeasure) feature.measure = f.measure ?? measures[0]?.name ?? null;
    if (canPeriodise && periodise) feature.periodise = { grain, n: Number.parseInt(periods, 10) };
    if (role === "inclusion") feature.keep_if = f.keep_if ?? { op: "==", value: 1 };
    return feature;
  }

  async function runPreview() {
    if (!f.label.trim()) {
      setLabelError(true);
      return;
    }
    setPreview({ state: "busy" });
    try {
      setPreview({ state: "done", result: await client.preview(read(), study) });
    } catch (error) {
      setPreview({
        state: "error",
        message: error instanceof Error ? error.message : String(error),
        issues: error instanceof ApiError ? error.issues : [],
      });
    }
  }

  function save() {
    if (!f.label.trim()) {
      setLabelError(true);
      return;
    }
    saveFeature(read(), editing.index);
    onClose();
  }

  const timing =
    role === "outcome"
      ? "Outcomes are counted after the index date, so 'from' is usually 1 or more."
      : "Must end before the index date: 'to' is -1 or earlier.";
  const counting =
    source.granularity === "year"
      ? " This source only records the year, so the window counts calendar years from the index year."
      : " Negative numbers are before the index date; 0 is the index day itself.";

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="md" aria-labelledby="feature-title">
      <DialogTitle id="feature-title">
        <Typography variant="overline" color="text.secondary" component="div">
          {existing ? `${ROLE_NAMES[role]} · ${existing.label}` : ROLE_NAMES[role]}
        </Typography>
        {existing ? "Edit" : "New"} {ROLE_NAMES[role]}
      </DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2.5}>
          <TextField
            label="Name"
            value={f.label}
            required
            autoFocus
            error={labelError}
            slotProps={{ htmlInput: { maxLength: 200 } }}
            helperText={
              labelError ? "Give the feature a name." : `Column in the analysis table: ${name}`
            }
            onChange={(e) => {
              setLabelError(false);
              setF({ ...f, label: e.target.value });
            }}
          />
          <FormControl>
            <InputLabel id="f-source-label">Data source</InputLabel>
            <Select
              labelId="f-source-label"
              label="Data source"
              value={f.source}
              onChange={(e) => {
                changeSource(e.target.value);
              }}
            >
              {meta.sources.map((s) => (
                <MenuItem key={s.name} value={s.name}>
                  {s.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {source.dimensions.map((d) => (
            <ValueMultiSelect
              key={`${source.name}/${d.name}`}
              source={source.name}
              dimension={d.name}
              label={d.label}
              helperText="Nothing picked means any"
              value={f.filters[d.name] ?? []}
              onChange={(values) => {
                const filters = Object.fromEntries(
                  Object.entries(f.filters).filter(([key]) => key !== d.name),
                );
                if (values.length) filters[d.name] = values;
                setF({ ...f, filters });
              }}
            />
          ))}

          <Box>
            <Typography variant="h3" sx={{ mb: 1 }}>
              Time window
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: "wrap", rowGap: 1 }}>
              {presetsFor(role, source, meta).map(([label, pFrom, pTo, unit]) => (
                <Chip
                  key={label}
                  label={label}
                  variant="outlined"
                  onClick={() => {
                    setFrom(String(pFrom));
                    setTo(String(pTo));
                    setF({ ...f, window: { ...f.window, unit } });
                  }}
                />
              ))}
            </Stack>
            <Stack direction="row" spacing={2}>
              <TextField
                label="From"
                type="number"
                value={from}
                onChange={(e) => {
                  setFrom(e.target.value);
                }}
              />
              <TextField
                label="To"
                type="number"
                value={to}
                onChange={(e) => {
                  setTo(e.target.value);
                }}
              />
              <FormControl sx={{ minWidth: 140 }}>
                <InputLabel id="f-unit-label">Unit</InputLabel>
                <Select
                  labelId="f-unit-label"
                  label="Unit"
                  value={f.window.unit}
                  onChange={(e) => {
                    setF({ ...f, window: { ...f.window, unit: e.target.value } });
                  }}
                >
                  {units.map((u) => (
                    <MenuItem key={u} value={u}>
                      {u}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
            <FormHelperText>{timing + counting}</FormHelperText>
          </Box>

          <FormControl>
            <InputLabel id="f-aggregation-label">Summarise as</InputLabel>
            <Select
              labelId="f-aggregation-label"
              label="Summarise as"
              value={allowed.includes(f.aggregation) ? f.aggregation : ""}
              onChange={(e) => {
                changeAggregation(e.target.value);
              }}
            >
              {allowed.map((a) => (
                <MenuItem key={a} value={a}>
                  {AGGREGATION_LABELS[a]}
                </MenuItem>
              ))}
            </Select>
            <FormHelperText>
              {meta.aggregations.find((a) => a.name === f.aggregation)?.description ?? ""}
            </FormHelperText>
          </FormControl>

          {needsMeasure && (
            <FormControl>
              <InputLabel id="f-measure-label">Measure</InputLabel>
              <Select
                labelId="f-measure-label"
                label="Measure"
                value={f.measure ?? measures[0]?.name ?? ""}
                onChange={(e) => {
                  setF({ ...f, measure: e.target.value });
                }}
              >
                {measures.map((m) => (
                  <MenuItem key={m.name} value={m.name}>
                    {m.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}

          {canPeriodise && (
            <Box>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={periodise}
                    onChange={(e) => {
                      setPeriodise(e.target.checked);
                    }}
                  />
                }
                label="Split the window into periods"
              />
              {periodise && (
                <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
                  <FormControl sx={{ minWidth: 140 }}>
                    <InputLabel id="f-grain-label">Period</InputLabel>
                    <Select
                      labelId="f-grain-label"
                      label="Period"
                      value={grain}
                      onChange={(e) => {
                        setGrain(e.target.value);
                      }}
                    >
                      {meta.period_grains.map((g) => (
                        <MenuItem key={g} value={g}>
                          {g}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <TextField
                    label="Number of periods"
                    type="number"
                    value={periods}
                    onChange={(e) => {
                      setPeriods(e.target.value);
                    }}
                  />
                </Stack>
              )}
            </Box>
          )}

          {role === "inclusion" && (
            <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
              <Typography variant="body2">Keep patients whose value is</Typography>
              <FormControl sx={{ minWidth: 160 }}>
                <InputLabel id="f-op-label">Test</InputLabel>
                <Select
                  labelId="f-op-label"
                  label="Test"
                  value={f.keep_if?.op ?? "=="}
                  onChange={(e) => {
                    setF({
                      ...f,
                      keep_if: { op: e.target.value, value: f.keep_if?.value ?? 1 },
                    });
                  }}
                >
                  {OPERATORS.map(([code, words]) => (
                    <MenuItem key={code} value={code}>
                      {words}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField
                label="Value"
                type="number"
                value={f.keep_if?.value ?? 1}
                onChange={(e) => {
                  setF({
                    ...f,
                    keep_if: { op: f.keep_if?.op ?? "==", value: Number(e.target.value) },
                  });
                }}
              />
            </Stack>
          )}

          <Box aria-live="polite">
            {preview.state === "busy" && (
              <Typography variant="body2" color="text.secondary">
                Counting…
              </Typography>
            )}
            {preview.state === "error" && (
              <Stack spacing={1}>
                <Alert severity="error">{preview.message}</Alert>
                <IssueList issues={preview.issues} />
              </Stack>
            )}
            {preview.state === "done" && (
              <Stack spacing={1}>
                <Table size="small" aria-label="Feature preview">
                  <TableHead>
                    <TableRow>
                      {["Column", "Group", "Patients", "Non-zero", "Mean", "Min", "Max"].map(
                        (h) => (
                          <TableCell key={h}>{h}</TableCell>
                        ),
                      )}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {preview.result.columns.flatMap((c) =>
                      (["treated", "control"] as const).map((group) => (
                        <TableRow key={`${c.column}-${group}`}>
                          <TableCell>{c.column}</TableCell>
                          <TableCell>{group === "treated" ? "Treated" : "Controls"}</TableCell>
                          <TableCell>{formatCount(c[group].n)}</TableCell>
                          <TableCell>{formatCount(c[group].nonzero)}</TableCell>
                          <TableCell>{formatNumber(c[group].mean)}</TableCell>
                          <TableCell>{formatNumber(c[group].min)}</TableCell>
                          <TableCell>{formatNumber(c[group].max)}</TableCell>
                        </TableRow>
                      )),
                    )}
                  </TableBody>
                </Table>
                <IssueList issues={preview.result.issues} />
              </Stack>
            )}
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={() => {
            void runPreview();
          }}
        >
          Preview values
        </Button>
        <Box sx={{ flexGrow: 1 }} />
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
