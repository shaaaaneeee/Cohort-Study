"""What a study draft still leaves open, so an agent can ask instead of assuming.

Left alone, an agent calling the MCP tools (Genie One, Genie Code, the AI
Playground) does not ask the user: in tests it stated its own assumptions and
ran. review() turns a partial draft
into the questions the user should answer, each with ready-made options. An
option carries the change it makes to the draft, so the agent can apply the
answer without guessing at the schema.

summary() describes a finished draft in plain words, for the user to confirm,
and confirmation_code() fingerprints it: run_study only runs the exact study
the user confirmed.
"""

import hashlib
import json
from typing import Any

from app.schemas.study import StudySpec

FOLLOW_UPS = [(6, "6 months"), (12, "12 months (default)"), (24, "24 months")]

# (aggregation, option shown to the user, feature label); {label} is the
# source's label as written in the mapping, e.g. "ED attendances".
MEASURES = [
    ("count", "Number of {label}", "{label}"),
    ("binary", "Any {label}, yes or no", "Any {label}"),
    ("time_to_first", "Time to the first of the {label}", "Time to first of the {label}"),
]


def _feature(
    source: dict, aggregation: str, months: int, role: str, label: str, start: int = 1
) -> dict:
    window = {"from": start, "to": start + months - 1, "unit": "months"}
    if role == "covariate":
        window = {"from": -months, "to": -1, "unit": "months"}
    return {
        "name": f"{source['name']}_{aggregation}_{role}"[:60].lower(),
        "label": label,
        "source": source["name"],
        "window": window,
        "aggregation": aggregation,
        "role": role,
    }


def _event_sources(meta: dict) -> list[dict]:
    """Sources recorded by day: the ones an outcome or a prior-use covariate can count."""
    return [s for s in meta["sources"] if s.get("granularity") == "day"]


def review(draft: dict[str, Any], meta: dict, condition_values: list[str]) -> dict[str, Any]:
    """The open choices in a (possibly partial) draft, as questions with options."""
    features = draft.get("features") or []
    roles = [f.get("role") for f in features]
    questions: list[dict[str, Any]] = []

    exposures = meta["exposures"]
    if not draft.get("exposure"):
        questions.append(
            {
                "id": "exposure",
                "question": "Which programme (exposure) should be evaluated?",
                "options": [
                    {"label": e["label"], "set": {"exposure": e["name"]}} for e in exposures
                ],
                "default": exposures[0]["name"] if len(exposures) == 1 else None,
            }
        )

    if "outcome" not in roles:
        options = []
        for source in _event_sources(meta):
            label = source["label"]
            for aggregation, text, feature_label in MEASURES:
                options.append(
                    {
                        "label": text.format(label=label),
                        "add_feature": _feature(
                            source,
                            aggregation,
                            12,
                            "outcome",
                            f"{feature_label.format(label=label)} in the 12 months after",
                        ),
                    }
                )
        questions.append(
            {
                "id": "outcome",
                "question": "What outcome should be measured after enrolment?",
                "options": options,
                "default": options[0]["label"] if options else None,
                "why": "The outcome decides the model: a count gives a rate ratio, yes/no an "
                "odds ratio, time to first event a hazard ratio.",
            }
        )
        questions.append(
            {
                "id": "follow_up",
                "question": "How long should patients be followed up?",
                "options": [
                    {"label": text, "outcome_window": {"from": 1, "to": m, "unit": "months"}}
                    for m, text in FOLLOW_UPS
                ],
                "default": "12 months (default)",
            }
        )

    has_covariates = bool(draft.get("person_covariates")) or "covariate" in roles
    if not has_covariates:
        options = [
            {"label": "Age and gender (default)", "set": {"person_covariates": ["age", "gender"]}},
            {
                "label": "Age, gender and ethnicity",
                "set": {"person_covariates": ["age", "gender", "ethnicity"]},
            },
        ]
        for source in _event_sources(meta):
            label = source["label"]
            options.append(
                {
                    "label": f"Also {label} in the 12 months before",
                    "add_feature": _feature(
                        source,
                        "count",
                        12,
                        "covariate",
                        f"{label} in the 12 months before",
                    ),
                }
            )
        questions.append(
            {
                "id": "covariates",
                "question": "What should the groups be matched and adjusted on? (several allowed)",
                "options": options,
                "default": "Age and gender (default)",
                "why": "Prior use matters most here: sicker patients enrol, so without it the "
                "programme can look harmful.",
            }
        )

    population_open = (
        draft.get("age_min") is None
        and draft.get("age_max") is None
        and not draft.get("person_filters")
        and "inclusion" not in roles
    )
    if population_open:
        population_options: list[dict[str, Any]] = [
            {"label": "Everyone in the data (default)", "set": {}},
            {"label": "Aged 65 and over", "set": {"age_min": 65}},
        ]
        condition = next((s for s in meta["sources"] if s["name"] == "condition"), None)
        if condition:
            for value in condition_values[:4]:
                population_options.append(
                    {
                        "label": f"Only patients with {value} before enrolment",
                        "add_feature": {
                            "name": f"has_{value}".lower().replace(" ", "_")[:60],
                            "label": f"{value} before enrolment",
                            "source": "condition",
                            "filters": {"condition_name": [value]},
                            "window": {"from": -5, "to": -1, "unit": "years"},
                            "aggregation": "binary",
                            "role": "inclusion",
                            "keep_if": {"op": "==", "value": 1},
                        },
                    }
                )
        questions.append(
            {
                "id": "population",
                "question": "Should the study be limited to a group of patients?",
                "options": population_options,
                "default": "Everyone in the data (default)",
            }
        )

    return {
        "open_questions": questions,
        "complete": not any(q["id"] in ("exposure", "outcome") for q in questions),
        "next": (
            "Ask the user these questions, showing the options and the default. Do not pick "
            "answers yourself. Apply each answer to the draft, then call check_study."
            if questions
            else "Nothing is open. Call check_study and show the user its summary to confirm."
        ),
    }


def summary(spec: StudySpec, meta: dict) -> list[str]:
    """The study in plain words, one line per part, for the user to confirm."""
    labels = {e["name"]: e["label"] for e in meta["exposures"]}
    lines = [
        f"Programme: {labels.get(spec.exposure, spec.exposure)}, compared with similar non-members"
    ]
    population = []
    if spec.age_min is not None or spec.age_max is not None:
        population.append(f"age {spec.age_min or 0} to {spec.age_max or 'any'}")
    for field, values in spec.person_filters.items():
        population.append(f"{field} in {', '.join(values)}")
    population += [f.label for f in spec.features if f.role == "inclusion"]
    lines.append("Population: " + ("; ".join(population) if population else "everyone in the data"))
    covariates = list(spec.person_covariates) + [
        f.label for f in spec.features if f.role == "covariate"
    ]
    lines.append("Matched and adjusted on: " + (", ".join(covariates) if covariates else "nothing"))
    for f in spec.features:
        if f.role == "outcome":
            w = f.window
            lines.append(
                f"Outcome: {f.label} ({f.aggregation}), "
                f"{w.from_} to {w.to} {w.unit} after enrolment"
            )
    lines.append(f"Random seed: {spec.seed}")
    return lines


def confirmation_code(spec: StudySpec) -> str:
    """A fingerprint of the exact study, so run_study runs what the user confirmed."""
    canonical = json.dumps(spec.model_dump(mode="json", by_alias=True), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:10]
