import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import CardHeader from "@mui/material/CardHeader";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import LinearProgress from "@mui/material/LinearProgress";
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

import { ValueMultiSelect } from "../../components/ValueMultiSelect";
import { useStudyStore } from "../../store/studyStore";
import { formatCount } from "../../utils/format";
import { readable } from "../../utils/study";
import { FeatureList } from "./FeatureList";

function age(text: string): number | null {
  const n = Number.parseInt(text, 10);
  return Number.isNaN(n) ? null : n;
}

function Bar({ n, first, color }: { n: number; first: number; color: "info" | "warning" }) {
  return (
    <Stack spacing={0.5}>
      <span>{formatCount(n)}</span>
      <LinearProgress
        variant="determinate"
        color={color}
        value={first ? Math.round((n / first) * 100) : 0}
        aria-hidden
      />
    </Stack>
  );
}

/** Step 1: who is in the study. Every control reads from and writes to the store. */
export function CohortStep({ onAddFeature }: { onAddFeature: (index: number | null) => void }) {
  const meta = useStudyStore((s) => s.meta);
  const study = useStudyStore((s) => s.study);
  const attrition = useStudyStore((s) => s.attrition);
  const setExposure = useStudyStore((s) => s.setExposure);
  const setAgeRange = useStudyStore((s) => s.setAgeRange);
  const setSeed = useStudyStore((s) => s.setSeed);
  const setPersonFilter = useStudyStore((s) => s.setPersonFilter);
  const setStep = useStudyStore((s) => s.setStep);
  if (!meta) return null;

  const steps = attrition.result?.steps ?? [];
  const first = steps[0];
  const small = attrition.result?.issues.filter((i) => i.code === "small_cell").length ?? 0;

  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h1">Who is in the study</Typography>
        <Typography color="text.secondary">
          The treatment group is everyone in the programme, indexed at their enrolment date.
          Controls never enrolled and are given a matching index date.
        </Typography>
      </Box>

      <Card>
        <CardHeader title="Treatment group" slotProps={{ title: { variant: "h2" } }} />
        <CardContent>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <FormControl sx={{ minWidth: 240 }}>
              <InputLabel id="exposure-label">Programme (treatment group)</InputLabel>
              <Select
                labelId="exposure-label"
                label="Programme (treatment group)"
                value={study.exposure}
                onChange={(e) => {
                  setExposure(e.target.value);
                }}
              >
                {meta.exposures.map((x) => (
                  <MenuItem key={x.name} value={x.name}>
                    {x.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="Youngest age"
              type="number"
              value={study.age_min ?? ""}
              slotProps={{ htmlInput: { min: 0, max: 120 } }}
              onChange={(e) => {
                setAgeRange(age(e.target.value), study.age_max ?? null);
              }}
            />
            <TextField
              label="Oldest age"
              type="number"
              value={study.age_max ?? ""}
              slotProps={{ htmlInput: { min: 0, max: 120 } }}
              onChange={(e) => {
                setAgeRange(study.age_min ?? null, age(e.target.value));
              }}
            />
            <TextField
              label="Seed"
              type="number"
              value={study.seed}
              helperText="Makes the controls' index dates repeatable."
              slotProps={{ htmlInput: { min: 0, step: 1 } }}
              onChange={(e) => {
                setSeed(Number.parseInt(e.target.value, 10));
              }}
            />
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title="Patient characteristics"
          subheader="Nothing picked means everyone."
          slotProps={{ title: { variant: "h2" } }}
        />
        <CardContent>
          <Stack spacing={2}>
            {meta.person_attributes.map((attribute) => (
              <ValueMultiSelect
                key={attribute}
                source="person"
                dimension={attribute}
                label={readable(attribute)}
                value={study.person_filters[attribute] ?? []}
                onChange={(values) => {
                  setPersonFilter(attribute, values);
                }}
              />
            ))}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={`Inclusion criteria (${study.features.filter((f) => f.role === "inclusion").length})`}
          slotProps={{ title: { variant: "h2" } }}
          action={
            <Button
              onClick={() => {
                onAddFeature(null);
              }}
            >
              + Add criterion
            </Button>
          }
        />
        <FeatureList
          role="inclusion"
          empty="No criteria: everyone in the person table is eligible."
          onEdit={onAddFeature}
        />
      </Card>

      <Card>
        <CardHeader
          title="Patients left after each step"
          slotProps={{ title: { variant: "h2" } }}
        />
        <Table size="small" aria-label="Attrition">
          <TableHead>
            <TableRow>
              <TableCell>Step</TableCell>
              <TableCell>Treated</TableCell>
              <TableCell>Controls</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {steps.map((s, i) => (
              <TableRow key={s.step} selected={i === steps.length - 1}>
                <TableCell>{s.step}</TableCell>
                <TableCell>
                  <Bar n={s.treated} first={first?.treated ?? 0} color="info" />
                </TableCell>
                <TableCell>
                  <Bar n={s.control} first={first?.control ?? 0} color="warning" />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <CardContent>
          <Typography variant="caption" color="text.secondary">
            {attrition.error
              ? attrition.error.designErrors
                ? "Counts appear once the design errors are fixed."
                : `Counts are not available: ${attrition.error.message}`
              : small
                ? `${small} of these counts are below the suppression threshold of 5. Do not share them as they are.`
                : "Matching will pair each treated patient with one control from this pool."}
          </Typography>
        </CardContent>
      </Card>

      <Stack direction="row" spacing={1} sx={{ justifyContent: "space-between" }}>
        <Button
          onClick={() => {
            setStep("ask");
          }}
        >
          ← Back to Ask
        </Button>
        <Button
          variant="contained"
          onClick={() => {
            setStep("features");
          }}
        >
          Next: Covariates and outcome
        </Button>
      </Stack>
    </Stack>
  );
}
