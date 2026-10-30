import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import { useColorScheme } from "@mui/material/styles";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { BarChart } from "@mui/x-charts/BarChart";
import { LineChart } from "@mui/x-charts/LineChart";
import type { ReactNode } from "react";

import { IssueList } from "../../components/IssueList";
import { resultsCurrent, useStudyStore } from "../../store/studyStore";
import { groupColors } from "../../theme/theme";
import type { AnalysisResult } from "../../types";
import { formatCount, formatNumber, formatP } from "../../utils/format";
import { readable } from "../../utils/study";

const SMD_LIMIT = 0.1;

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <Card>
      <CardContent>
        <Typography variant="caption" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h2">{value}</Typography>
        {note && (
          <Typography variant="caption" color="text.secondary">
            {note}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

function ChartCard({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader title={title} subheader={hint} slotProps={{ title: { variant: "h2" } }} />
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function covariateLabel(column: string, labels: Map<string, string>): string {
  const [name, level] = column.split("=");
  const base = labels.get(name ?? column) ?? readable(name ?? column);
  return level === undefined ? base : `${base}: ${level}`;
}

function Answer({ r }: { r: AnalysisResult }) {
  const m = r.model;
  const ok = m.ci_low !== null && m.ci_high !== null && (m.ci_low > 1 || m.ci_high < 1);
  return (
    <Card>
      <CardContent>
        <Typography variant="overline" color="text.secondary">
          {m.measure}
        </Typography>
        <Stack direction="row" spacing={2} sx={{ alignItems: "baseline", flexWrap: "wrap" }}>
          <Typography variant="h1" component="p" sx={{ fontSize: "2.4rem" }}>
            {formatNumber(m.estimate)}
          </Typography>
          <Typography color="text.secondary">
            95% CI {formatNumber(m.ci_low)} to {formatNumber(m.ci_high)} · {formatP(m.p_value)}
          </Typography>
          <Chip
            size="small"
            color={ok ? "success" : "default"}
            label={ok ? "Interval excludes 1" : "Consistent with no effect"}
          />
        </Stack>
        <Typography sx={{ mt: 1.5 }}>{r.interpretation}</Typography>
        <Typography variant="caption" color="text.secondary">
          {m.name}
        </Typography>
      </CardContent>
    </Card>
  );
}

function BalanceSection({ r, labels }: { r: AnalysisResult; labels: Map<string, string> }) {
  const { mode, systemMode } = useColorScheme();
  const colors = groupColors[(mode === "system" ? systemMode : mode) === "dark" ? "dark" : "light"];
  if (!r.balance.length) return null;
  const rows = r.balance.map((b) => ({
    covariate: covariateLabel(b.covariate, labels),
    before: Math.abs(b.smd_before ?? 0),
    after: Math.abs(b.smd_after ?? 0),
  }));
  return (
    <ChartCard
      title="Covariate balance"
      hint={`Standardised mean difference before and after matching. Under ${SMD_LIMIT} is balanced.`}
    >
      <BarChart
        height={Math.max(220, rows.length * 34 + 60)}
        layout="horizontal"
        dataset={rows}
        yAxis={[{ scaleType: "band", dataKey: "covariate", width: 160 }]}
        xAxis={[{ label: "|SMD|" }]}
        series={[
          { dataKey: "before", label: "Before matching", color: colors.before },
          { dataKey: "after", label: "After matching", color: colors.treated },
        ]}
      />
      <Table size="small" aria-label="Balance table">
        <TableHead>
          <TableRow>
            <TableCell>Covariate</TableCell>
            <TableCell align="right">Treated (after)</TableCell>
            <TableCell align="right">Controls (after)</TableCell>
            <TableCell align="right">SMD before</TableCell>
            <TableCell align="right">SMD after</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {r.balance.map((b) => (
            <TableRow key={b.covariate}>
              <TableCell>{covariateLabel(b.covariate, labels)}</TableCell>
              <TableCell align="right">{formatNumber(b.treated_mean_after)}</TableCell>
              <TableCell align="right">{formatNumber(b.control_mean_after)}</TableCell>
              <TableCell align="right">{formatNumber(b.smd_before)}</TableCell>
              <TableCell
                align="right"
                sx={{ color: Math.abs(b.smd_after ?? 0) >= SMD_LIMIT ? "warning.main" : undefined }}
              >
                {formatNumber(b.smd_after)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </ChartCard>
  );
}

function Plots({ r }: { r: AnalysisResult }) {
  const { mode, systemMode } = useColorScheme();
  const colors = groupColors[(mode === "system" ? systemMode : mode) === "dark" ? "dark" : "light"];
  const { propensity, survival, periods } = r.plots;
  return (
    <>
      {propensity && (
        <ChartCard
          title="Propensity score overlap"
          hint="Share of each group in each score band. Treated patients where hardly any controls lie have no good comparison."
        >
          <Grid container spacing={2}>
            {(["before", "after"] as const).map((stage) => (
              <Grid key={stage} size={{ xs: 12, md: 6 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {stage === "before" ? "Before matching" : "After matching"}
                </Typography>
                <LineChart
                  height={220}
                  xAxis={[{ data: propensity.edges.slice(0, -1), label: "Propensity score" }]}
                  series={[
                    {
                      data: propensity[stage].treated,
                      label: "Treated",
                      color: colors.treated,
                      showMark: false,
                    },
                    {
                      data: propensity[stage].control,
                      label: "Controls",
                      color: colors.control,
                      showMark: false,
                    },
                  ]}
                />
              </Grid>
            ))}
          </Grid>
        </ChartCard>
      )}
      {survival && (
        <ChartCard
          title="Survival without the outcome"
          hint="Kaplan-Meier curves. Curves that cross or converge mean one hazard ratio summarises them poorly."
        >
          <LineChart
            height={260}
            xAxis={[{ data: survival.days, label: "Days since the index date" }]}
            yAxis={[{ min: 0, max: 1 }]}
            series={[
              { data: survival.treated, label: "Treated", color: colors.treated, showMark: false },
              { data: survival.control, label: "Controls", color: colors.control, showMark: false },
            ]}
          />
        </ChartCard>
      )}
      {periods && (
        <ChartCard title="Outcome by period" hint="Mean per patient in each period, by group.">
          <LineChart
            height={260}
            xAxis={[{ scaleType: "point", data: periods.periods }]}
            series={[
              { data: periods.treated, label: "Treated", color: colors.treated },
              { data: periods.control, label: "Controls", color: colors.control },
            ]}
          />
        </ChartCard>
      )}
    </>
  );
}

/** Step 3: the estimate, how far to trust it, and the charts behind it. */
export function ResultsStep() {
  const state = useStudyStore();
  const { run, study } = state;
  const current = resultsCurrent(state);
  const labels = new Map(study.features.map((f) => [f.name, f.label]));

  if (run.running) {
    return (
      <Stack spacing={2}>
        <Typography variant="h1">Results</Typography>
        <LinearProgress />
        <Typography color="text.secondary">Matching and fitting the model…</Typography>
      </Stack>
    );
  }
  if (run.error) {
    return (
      <Stack spacing={2}>
        <Typography variant="h1">Results</Typography>
        <Alert severity="error">
          <AlertTitle>The analysis could not run</AlertTitle>
          {run.error.message}
        </Alert>
        <IssueList issues={run.error.issues.filter((i) => i.code !== "analysis_failed")} />
      </Stack>
    );
  }
  const r = run.result;
  if (!r) {
    return (
      <Stack spacing={1}>
        <Typography variant="h1">Results</Typography>
        <Typography color="text.secondary">
          Nothing has run yet. Build the study in steps 1 and 2, then press Run analysis.
        </Typography>
      </Stack>
    );
  }

  const treatedPct = r.cohort.treated
    ? Math.round((r.cohort.treated_matched / r.cohort.treated) * 100)
    : 0;
  return (
    <Stack spacing={2}>
      <Typography variant="h1">Results</Typography>
      {!current && (
        <Alert severity="warning">
          The study has changed since this ran. Run it again to bring the results up to date.
        </Alert>
      )}
      <Answer r={r} />
      <Grid container spacing={2}>
        <Grid size={{ xs: 6, md: 3 }}>
          <Tile
            label="Treated analysed"
            value={formatCount(r.cohort.treated_matched)}
            note={`${treatedPct}% of ${formatCount(r.cohort.treated)}`}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Tile
            label="Controls analysed"
            value={formatCount(r.cohort.control_matched)}
            note={`of ${formatCount(r.cohort.control)}`}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Tile label="Treated with the outcome" value={formatCount(r.events.treated)} />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <Tile label="Controls with the outcome" value={formatCount(r.events.control)} />
        </Grid>
      </Grid>
      <Card>
        <CardHeader title="How far to trust it" slotProps={{ title: { variant: "h2" } }} />
        <CardContent>
          {r.issues.length ? (
            <IssueList issues={r.issues} labelFor={(name) => labels.get(name) ?? name} />
          ) : (
            <Alert severity="success">
              No warnings: matching balanced the groups and the model fitted cleanly.
            </Alert>
          )}
        </CardContent>
      </Card>
      <BalanceSection r={r} labels={labels} />
      <Box>
        <Stack spacing={2}>
          <Plots r={r} />
        </Stack>
      </Box>
    </Stack>
  );
}
