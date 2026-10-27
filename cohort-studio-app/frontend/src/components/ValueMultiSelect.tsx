import Autocomplete from "@mui/material/Autocomplete";
import Chip from "@mui/material/Chip";
import TextField from "@mui/material/TextField";

import { useApi } from "../api/context";
import { useDimensionValues } from "../hooks/useDimensionValues";

interface Props {
  source: string;
  dimension: string;
  label: string;
  value: string[];
  onChange: (values: string[]) => void;
  helperText?: string;
}

/** Pick any number of a dimension's values; none picked means any value. */
export function ValueMultiSelect({ source, dimension, label, value, onChange, helperText }: Props) {
  const client = useApi();
  const { values, loading, error } = useDimensionValues(client, source, dimension);
  // Values the study holds stay visible even before the list has loaded.
  const options = Array.from(new Set([...values, ...value]));
  return (
    <Autocomplete
      multiple
      disableCloseOnSelect
      options={options}
      value={value}
      loading={loading}
      onChange={(_, chosen) => {
        onChange(chosen);
      }}
      renderValue={(selected, getItemProps) =>
        selected.map((option, index) => {
          const { key, ...itemProps } = getItemProps({ index });
          return <Chip key={key} label={option} size="small" {...itemProps} />;
        })
      }
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          placeholder={value.length ? "" : "Any"}
          error={Boolean(error)}
          helperText={error ? `Could not load values: ${error}` : helperText}
        />
      )}
    />
  );
}
