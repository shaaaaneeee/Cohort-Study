import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";
import { IssueList } from "../../components/IssueList";
import { useStudyStore } from "../../store/studyStore";
import type { Role } from "../../types";
import { describe } from "../../utils/study";

interface Props {
  role: Role;
  empty: string | null;
  onEdit: (index: number) => void;
}

/** The study's features of one role, each with its own issues, Edit and Remove. */
export function FeatureList({ role, empty, onEdit }: Props) {
  const meta = useStudyStore((s) => s.meta);
  const features = useStudyStore((s) => s.study.features);
  const issues = useStudyStore((s) => s.check.issues);
  const removeFeature = useStudyStore((s) => s.removeFeature);
  const [removing, setRemoving] = useState<number | null>(null);

  const items = features
    .map((feature, index) => ({ feature, index }))
    .filter(({ feature }) => feature.role === role);

  if (!items.length) {
    return empty ? (
      <Typography variant="body2" color="text.secondary" sx={{ px: 2, py: 1.5 }}>
        {empty}
      </Typography>
    ) : null;
  }

  return (
    <>
      <List disablePadding aria-label={`${role} list`}>
        {items.map(({ feature, index }, n) => {
          const own = issues.filter((i) => i.feature === feature.name);
          const hasError = own.some((i) => i.level === "error");
          return (
            <ListItem
              key={feature.name || index}
              divider
              sx={{
                alignItems: "flex-start",
                gap: 2,
                borderLeft: 3,
                borderLeftColor: hasError ? "error.main" : "transparent",
              }}
            >
              {role === "inclusion" && (
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 20, pt: 0.25 }}>
                  {n + 1}
                </Typography>
              )}
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Typography variant="body1" sx={{ fontWeight: 600 }}>
                  {feature.label}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {describe(feature, meta)}
                </Typography>
                {own.length > 0 && (
                  <Box sx={{ mt: 1 }}>
                    <IssueList issues={own} />
                  </Box>
                )}
              </Box>
              <Stack direction="row" spacing={0.5}>
                <Button
                  size="small"
                  aria-label={`Edit ${feature.label}`}
                  onClick={() => {
                    onEdit(index);
                  }}
                >
                  Edit
                </Button>
                <Button
                  size="small"
                  color="inherit"
                  aria-label={`Remove ${feature.label}`}
                  onClick={() => {
                    setRemoving(index);
                  }}
                >
                  Remove
                </Button>
              </Stack>
            </ListItem>
          );
        })}
      </List>
      <ConfirmDialog
        open={removing !== null}
        title="Remove this feature?"
        message={`"${removing !== null ? (features[removing]?.label ?? "") : ""}" will be removed from the study.`}
        confirmLabel="Remove"
        onConfirm={() => {
          if (removing !== null) removeFeature(removing);
        }}
        onClose={() => {
          setRemoving(null);
        }}
      />
    </>
  );
}
