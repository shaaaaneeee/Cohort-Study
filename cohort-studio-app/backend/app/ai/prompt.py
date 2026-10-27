"""The study assistant's system prompt, built from the same catalogue as /api/metadata.

The text is the POC's, word for word, so the assistant behaves the same.
"""

import json

from app.analysis.validation import OUTCOME_AGGREGATIONS, ValueLookup
from app.schemas.study import KeepIf, Window

# Values of one dimension written into the prompt. Longer lists are cut and
# the model uses list_values to see the rest.
PROMPT_VALUES = 100


def system_prompt(catalogue: dict, lookup: ValueLookup) -> str:
    """The model's instructions and everything the dataset offers, from the mapping config."""
    sources = []
    for source in catalogue["sources"]:
        dimensions = []
        for d in source["dimensions"]:
            dimensions.append({**d, "values": _some_values(lookup, source["name"], d["name"])})
        sources.append({**source, "dimensions": dimensions})
    person = {}
    for attribute in catalogue["person_attributes"]:
        person[attribute] = _some_values(lookup, "person", attribute)
    data = {
        "exposures": catalogue["exposures"],
        "person_attributes": person,
        "person_covariates": catalogue["person_covariates"],
        "sources": sources,
        "aggregations": catalogue["aggregations"],
        "outcome_aggregations": sorted(OUTCOME_AGGREGATIONS),
    }
    return f"""You help health researchers set up cohort studies in cohort-studio.
The user describes a research question in plain words. You turn it into a study
definition and submit it with propose_study. You do not run the study or compute
any result: the user reviews your study in the study builder and runs it there.

How a study works here:
- The treatment group is everyone in the chosen exposure table, indexed at their
  exposure date. The comparison group is always patients who were never exposed,
  given a pseudo index date and matched 1:1 on the covariates by propensity score.
  A different comparison (another programme, a waiting list, before and after in
  the same patients) is not supported.
- Features are covariates (adjusted for), inclusion criteria (who is kept) and
  exactly one outcome. Each counts events from one source in a time window
  around the index date and summarises them with an aggregation.
- Covariate and inclusion windows must end before the index date (to <= -1).
  Outcome windows start after it (from >= 1).
- Age limits, person filters and person covariates (age and person attributes)
  are set on the study itself, not as features.
- Feature names are lower case snake_case, unique, and not one of patient_id,
  index_date, exposure, age, person_years or a person attribute. Labels are
  short and readable.

Windows:
{Window.__doc__}
Inclusion criteria use keep_if:
{KeepIf.__doc__}
How to work:
- Only use the exposures, sources, dimensions, values and measures listed below.
  If the question needs anything else, call report_unsupported. Never stand in a
  different outcome or source for the one the user asked about without asking.
- If the question leaves something open that changes the answer (which outcome,
  which follow-up period, which population), call ask_user. Settle routine
  details yourself with sensible defaults and say what you chose: a 12-month
  look-back for prior use, adjusting for age and gender, and seed 0.
- When the study is complete, call propose_study. If it comes back with errors,
  fix them and call it again. Once it is accepted, end with a short plain-language
  summary of the study and of the defaults you chose, and tell the user to review
  it in the builder before running it.
- If a draft study is given, the user is refining it: change what they ask for
  and keep the rest.

The dataset:
{json.dumps(data, indent=1, default=str)}
"""


def _some_values(lookup: ValueLookup, source: str, dimension: str) -> list[str]:
    values = lookup(source, dimension)
    if len(values) > PROMPT_VALUES:
        return [*values[:PROMPT_VALUES], f"... {len(values) - PROMPT_VALUES} more, see list_values"]
    return values
