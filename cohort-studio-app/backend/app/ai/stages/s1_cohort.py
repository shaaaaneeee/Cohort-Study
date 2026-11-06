"""S1 Cohort: who is in the study.

Age limits, person filters and inclusion criteria. There is always a
cohort once there is a draft (everyone exposed and their never-exposed
comparisons), so this stage is done with the draft; the size check in
S4 decides whether the cohort is big enough.
"""

from app.ai.stages.base import Stage
from app.schemas.study import StudySpec


def done(draft: StudySpec | None) -> bool:
    return draft is not None


STAGE = Stage(
    id="cohort",
    title="Cohort",
    goal="Decide who is in the study: age limits, person filters and inclusion criteria.",
    instructions=(
        "Apply every restriction the user states (age, gender, ethnicity, residence, "
        "conditions before index). Do not add restrictions they did not ask for. If "
        "they mention a population loosely ('older patients', 'diabetics'), ask "
        "with options such as 'Age 65 and over'."
    ),
    done=done,
)
