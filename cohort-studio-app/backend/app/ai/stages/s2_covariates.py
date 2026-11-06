"""S2 Covariates: what the comparison adjusts for.

Done when the draft adjusts for at least one thing, a person covariate
(age, gender, ...) or a covariate feature (prior use, conditions).
"""

from app.ai.stages.base import Stage
from app.schemas.study import StudySpec


def done(draft: StudySpec | None) -> bool:
    if draft is None:
        return False
    return bool(draft.person_covariates) or any(f.role == "covariate" for f in draft.features)


STAGE = Stage(
    id="covariates",
    title="Covariates",
    goal="Choose what the groups are matched and adjusted on.",
    instructions=(
        "Default to age, gender and prior use of the outcome in the 12 months before "
        "index, and say so. Add what the user asks for. If they ask what to adjust "
        "for, suggest the likely confounders as options rather than deciding alone."
    ),
    done=done,
)
