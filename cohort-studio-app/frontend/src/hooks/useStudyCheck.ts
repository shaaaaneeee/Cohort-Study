// Re-check the study and recount the cohort whenever it changes, by hand or
// by the assistant. Quick edits start several rounds; only the latest
// round's answers are kept, in whatever order the responses arrive.
import { useEffect, useRef } from "react";

import type { ApiClient } from "../api/client";
import { ApiError } from "../api/client";
import { useStudyStore } from "../store/studyStore";

export function useStudyCheck(client: ApiClient, delay = 300): void {
  const revision = useStudyStore((s) => s.revision);
  const hasMeta = useStudyStore((s) => s.meta !== null);
  const round = useRef(0);

  useEffect(() => {
    if (!hasMeta) return;
    const timer = setTimeout(() => {
      const mine = ++round.current;
      const { study, setCheck, setAttrition } = useStudyStore.getState();
      void Promise.allSettled([client.check(study), client.attrition(study)]).then(
        ([check, attrition]) => {
          if (mine !== round.current) return;
          if (check.status === "fulfilled") {
            setCheck({ issues: check.value.issues, model: check.value.model });
          } else {
            const e: unknown = check.reason;
            const issues = e instanceof ApiError && e.issues.length ? e.issues : [];
            const message = e instanceof Error ? e.message : String(e);
            setCheck({
              issues: issues.length
                ? issues
                : [{ level: "error", code: "request_failed", message, feature: null }],
              model: null,
            });
          }
          if (attrition.status === "fulfilled") {
            setAttrition({ result: attrition.value, error: null });
          } else {
            const e: unknown = attrition.reason;
            setAttrition({
              result: null,
              error: {
                message: e instanceof Error ? e.message : String(e),
                designErrors: e instanceof ApiError && e.issues.length > 0,
              },
            });
          }
        },
      );
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [revision, hasMeta, client, delay]);
}
