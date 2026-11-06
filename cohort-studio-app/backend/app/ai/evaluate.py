"""Check how well the study assistant turns questions into studies, against the running API.

Run it inside the backend container (Northflank: cs-backend -> Shell), where
the LLM gateway is reachable and the LLM settings are already set:

    python -m app.ai.evaluate              # every case
    python -m app.ai.evaluate --case 4 15  # only some cases
    python -m app.ai.evaluate --verbose    # also print each reply and draft

Each case sends one question to POST /api/chat (and a follow-up answer when
the assistant asks something), then checks the study it drafted: status,
exposure, age limits, person filters, covariates, inclusion criteria and the
outcome. It prints a line per check and a score at the end. Nothing is
written anywhere; the API only reads the database.

The expected values come from the synthetic dataset in the cohort schema
(conditions such as diabetes and copd, triage levels P1-P4, arrival modes
SCDF, Own transport and Private ambulance, dispositions Admitted and
Discharged). A real model can phrase a study in more than one valid way, so
each check accepts every reasonable form, for example "12 months after" as
1..12 months, 1..365 days or 1..1 years.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

Draft = dict[str, Any]
Check = tuple[str, Callable[[Draft], bool]]


# ------------------------------------------------------------------ helpers


def features(d: Draft, role: str) -> list[dict]:
    return [f for f in d.get("features", []) if f.get("role") == role]


def outcome(d: Draft) -> dict:
    found = features(d, "outcome")
    return found[0] if found else {}


def window_is(f: dict, months: int, after: bool = True) -> bool:
    """True if the window covers `months` months after (or before) the index date, in any unit."""
    w = f.get("window") or {}
    lo, hi, unit = w.get("from"), w.get("to"), w.get("unit")
    days = range(months * 28, months * 31 + 1)  # 12 months: 336-372 days
    if after:
        return lo == 1 and (
            (unit == "months" and hi == months)
            or (unit == "days" and hi in days)
            or (unit == "years" and months % 12 == 0 and hi == months // 12)
        )
    return hi == -1 and (
        (unit == "months" and lo == -months)
        or (unit == "days" and lo is not None and -lo in days)
        or (unit == "years" and months % 12 == 0 and lo == -(months // 12))
    )


def filter_values(f_or_d: dict, key: str, field: str = "filters") -> set[str]:
    return {str(v).lower() for v in (f_or_d.get(field) or {}).get(key, [])}


def has_condition_inclusion(d: Draft, condition: str, present: bool) -> bool:
    """An inclusion criterion keeping patients with (or without) a condition before index."""
    keeps_with = {("==", 1), (">=", 1), (">", 0)}
    keeps_without = {("==", 0), ("!=", 1), ("<", 1), ("<=", 0)}
    for f in features(d, "inclusion"):
        if f.get("source") != "condition" or condition not in filter_values(f, "condition_name"):
            continue
        keep = f.get("keep_if") or {}
        rule = (keep.get("op"), keep.get("value"))
        if rule in (keeps_with if present else keeps_without):
            return True
    return False


def covariate_on(d: Draft, source: str) -> bool:
    return any(f.get("source") == source for f in features(d, "covariate"))


def ages(d: Draft, lo: int | None, hi: int | None) -> bool:
    return d.get("age_min") == lo and d.get("age_max") == hi


# -------------------------------------------------------------------- cases

READY = "ready"
Q = "Does Programme A reduce ED attendances in the 12 months after enrolment"

BASE_CHECKS: list[Check] = [
    ("exposure is Programme A", lambda d: d.get("exposure") == "program_a"),
    ("outcome is ED attendances", lambda d: outcome(d).get("source") == "ed_episodes"),
    ("outcome window is the 12 months after", lambda d: window_is(outcome(d), 12)),
]

CASES: list[dict[str, Any]] = [
    {
        "id": 1,
        "name": "complete question",
        "ask": Q + "?",
        "status": READY,
        "checks": BASE_CHECKS,
    },
    {
        "id": 2,
        "name": "women only",
        "ask": Q + ", for women only?",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            (
                "person filter gender = F",
                lambda d: filter_values(d, "gender", "person_filters") == {"f"},
            ),
        ],
    },
    {
        "id": 3,
        "name": "men aged 60 and over",
        "ask": Q + ", among men aged 60 and over?",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            (
                "person filter gender = M",
                lambda d: filter_values(d, "gender", "person_filters") == {"m"},
            ),
            ("age_min = 60, no age_max", lambda d: ages(d, 60, None)),
        ],
    },
    {
        "id": 4,
        "name": "adults with diabetes",
        "ask": Q + ", for adults with diabetes?",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            ("age_min = 18", lambda d: d.get("age_min") == 18),
            (
                "inclusion: diabetes before enrolment",
                lambda d: has_condition_inclusion(d, "diabetes", True),
            ),
        ],
    },
    {
        "id": 5,
        "name": "exclude a condition",
        "ask": Q + ", excluding patients with COPD?",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            (
                "inclusion: no COPD before enrolment",
                lambda d: has_condition_inclusion(d, "copd", False),
            ),
        ],
    },
    {
        "id": 6,
        "name": "adjust for prior ED use",
        "ask": Q + "? Adjust for ED attendances in the year before enrolment.",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            ("covariate: prior ED attendances", lambda d: covariate_on(d, "ed_episodes")),
            (
                "prior ED window is the 12 months before",
                lambda d: any(
                    window_is(f, 12, after=False)
                    for f in features(d, "covariate")
                    if f.get("source") == "ed_episodes"
                ),
            ),
        ],
    },
    {
        "id": 7,
        "name": "outcome filtered by disposition",
        "ask": "Does Programme A reduce ED attendances that end in admission, in the 6 months after enrolment?",
        "status": READY,
        "checks": [
            ("exposure is Programme A", lambda d: d.get("exposure") == "program_a"),
            ("outcome is ED attendances", lambda d: outcome(d).get("source") == "ed_episodes"),
            (
                "outcome filter disposition = Admitted",
                lambda d: filter_values(outcome(d), "disposition") == {"admitted"},
            ),
            ("outcome window is the 6 months after", lambda d: window_is(outcome(d), 6)),
        ],
    },
    {
        "id": 8,
        "name": "outcome filtered by arrival mode",
        "ask": Q + "? Count only attendances where the patient arrived by SCDF ambulance.",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            (
                "outcome filter mode_of_arrival = SCDF",
                lambda d: filter_values(outcome(d), "mode_of_arrival") == {"scdf"},
            ),
        ],
    },
    {
        "id": 9,
        "name": "outcome filtered by triage",
        "ask": Q + "? Count only high-acuity attendances, triage P1 and P2.",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            (
                "outcome filter triage_level = P1, P2",
                lambda d: filter_values(outcome(d), "triage_level") == {"p1", "p2"},
            ),
        ],
    },
    {
        "id": 10,
        "name": "several person filters",
        "ask": Q + ", among Malay and Indian citizens?",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            (
                "ethnicity = Malay, Indian",
                lambda d: filter_values(d, "ethnicity", "person_filters") == {"malay", "indian"},
            ),
            (
                "residence_status = Citizen",
                lambda d: filter_values(d, "residence_status", "person_filters") == {"citizen"},
            ),
        ],
    },
    {
        "id": 11,
        "name": "time to first event",
        "ask": "Does Programme A delay the first ED attendance after enrolment? Follow patients for 12 months.",
        "status": READY,
        "checks": [
            ("exposure is Programme A", lambda d: d.get("exposure") == "program_a"),
            (
                "outcome aggregation is time_to_first",
                lambda d: outcome(d).get("aggregation") == "time_to_first",
            ),
            ("outcome window is the 12 months after", lambda d: window_is(outcome(d), 12)),
        ],
    },
    {
        "id": 12,
        "name": "unsupported: length of stay as the outcome",
        # Outcomes must be counts, binary, rates or time to first event; a mean of a
        # measure (length of stay) is allowed for covariates only, so the model
        # should say the study cannot be set up as asked.
        "ask": "Does Programme A change the average ED length of stay in the 12 months after "
        "enrolment?",
        "status": "unsupported",
        "checks": [],
    },
    {
        "id": 13,
        "name": "unsupported: mortality",
        "ask": "Does Programme A reduce mortality?",
        "status": "unsupported",
        "checks": [],
    },
    {
        "id": 14,
        "name": "unsupported: GP visits",
        "ask": "Does Programme A reduce GP visits in the year after enrolment?",
        "status": "unsupported",
        "checks": [],
    },
    {
        "id": 15,
        "name": "ambiguous, then answered",
        "ask": "Does Programme A help patients?",
        "first_status": "asking",
        "answer": "Use any ED attendance in the 12 months after enrolment, for adults with diabetes.",
        "status": READY,
        "checks": [
            ("exposure is Programme A", lambda d: d.get("exposure") == "program_a"),
            ("outcome is ED attendances", lambda d: outcome(d).get("source") == "ed_episodes"),
            ("outcome window is the 12 months after", lambda d: window_is(outcome(d), 12)),
            (
                "inclusion: diabetes before enrolment",
                lambda d: has_condition_inclusion(d, "diabetes", True),
            ),
        ],
    },
    {
        "id": 16,
        "name": "edit an existing study (manual edits kept)",
        "draft_from": 1,
        "edit_draft": lambda d: {**d, "age_min": 40},
        "ask": "Now restrict it to women and also adjust for ethnicity.",
        "status": READY,
        "checks": [
            *BASE_CHECKS,
            (
                "person filter gender = F",
                lambda d: filter_values(d, "gender", "person_filters") == {"f"},
            ),
            (
                "ethnicity is a person covariate",
                lambda d: "ethnicity" in (d.get("person_covariates") or []),
            ),
            ("manual edit kept: age_min = 40", lambda d: d.get("age_min") == 40),
        ],
    },
]


# ------------------------------------------------------------------ running


def post_chat(url: str, messages: list[dict], draft: Draft | None, timeout: float) -> dict:
    body = json.dumps({"messages": messages, "draft": draft}).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = os.environ.get("API_KEY")
    if key:
        headers["X-API-Key"] = key
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("message", "")
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {e.code} {detail}".strip()) from None


def run_case(
    case: dict, url: str, timeout: float, drafts: dict[int, Draft], verbose: bool
) -> tuple[int, int]:
    print(f"\n[{case['id']:>2}] {case['name']}")
    draft = None
    if "draft_from" in case:
        draft = drafts.get(case["draft_from"])
        if draft is None:
            print(f"     SKIP  needs case {case['draft_from']} to pass first")
            return 0, 1
        draft = case["edit_draft"](draft) if "edit_draft" in case else draft

    messages = [{"role": "user", "content": case["ask"]}]
    started = time.monotonic()
    try:
        result = post_chat(url, messages, draft, timeout)
        if "answer" in case:
            ok = result["status"] == case.get("first_status", "asking")
            print(
                f"     {'PASS' if ok else 'FAIL'}  first reply asks a question (status {result['status']})"
            )
            messages += [
                {"role": "assistant", "content": result["reply"] or "Questions asked."},
                {"role": "user", "content": case["answer"]},
            ]
            result = post_chat(url, messages, result.get("draft") or draft, timeout)
            first = (1 if ok else 0, 1)
        else:
            first = (0, 0)
    except Exception as e:
        print(f"     FAIL  request failed: {e}")
        return 0, 1 + len(case["checks"])
    seconds = time.monotonic() - started

    passed, total = first
    ok = result["status"] == case["status"]
    passed, total = passed + ok, total + 1
    print(
        f"     {'PASS' if ok else 'FAIL'}  status {result['status']} (expected {case['status']})  [{seconds:.0f}s]"
    )

    d = result.get("draft") or {}
    for label, check in case["checks"]:
        try:
            ok = bool(d) and check(d)
        except Exception:
            ok = False
        passed, total = passed + ok, total + 1
        print(f"     {'PASS' if ok else 'FAIL'}  {label}")

    errors = [i for i in result.get("issues", []) if i.get("level") == "error"]
    if errors:
        print(
            f"     note  {len(errors)} design error(s): "
            + "; ".join(i.get("message", "") for i in errors)
        )
    if verbose:
        print("     reply: " + result.get("reply", "").replace("\n", " ")[:500])
        if result.get("questions"):
            print("     questions: " + " | ".join(result["questions"]))
        print("     draft: " + json.dumps(d))
    if d and result["status"] == READY:
        drafts[case["id"]] = d
    return passed, total


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the study assistant on fixed questions.")
    parser.add_argument(
        "--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/api/chat"
    )
    parser.add_argument("--case", type=int, nargs="*", help="case numbers to run (default: all)")
    parser.add_argument("--timeout", type=float, default=240.0, help="seconds per request")
    parser.add_argument("--verbose", action="store_true", help="print replies and drafts")
    args = parser.parse_args()

    if not os.environ.get("LLM_API_KEY") or os.environ.get("LLM_PROVIDER") in ("demo", "scripted"):
        print(
            "Note: no LLM_API_KEY (or LLM_PROVIDER is demo/scripted), so the scripted demo "
            "answers instead of the real model. Scores will be low and mean nothing."
        )

    selected = [c for c in CASES if not args.case or c["id"] in args.case]
    needed = {c["draft_from"] for c in selected if "draft_from" in c}
    selected = [c for c in CASES if c in selected or c["id"] in needed]

    drafts: dict[int, Draft] = {}
    passed = total = 0
    for case in selected:
        p, t = run_case(case, args.url, args.timeout, drafts, args.verbose)
        passed, total = passed + p, total + t

    score = 100 * passed / total if total else 0
    print(f"\nScore: {passed}/{total} checks passed ({score:.0f}%) across {len(selected)} cases")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
