"""S0 Question: what is compared, and what "works" means.

Done once there is a draft study: drafting needs the exposure, so the
question has been understood well enough to start.
"""

from app.ai.stages.base import Stage
from app.schemas.study import StudySpec


def done(draft: StudySpec | None) -> bool:
    return draft is not None


STAGE = Stage(
    id="question",
    title="Question",
    goal="Understand the research question: which exposure, and what effect the user means.",
    instructions=(
        "Identify the exposure from the listed exposures. If the question names an "
        "effect that is not in the data (for example mortality or cost), call "
        "report_unsupported. If the effect is vague ('does it help?'), ask what "
        "outcome they mean, offering the measures this data has."
    ),
    done=done,
)
