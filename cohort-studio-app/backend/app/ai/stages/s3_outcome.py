"""S3 Outcome: what is measured after the index date, and how.

Done when the draft has its one outcome feature.
"""

from app.ai.stages.base import Stage
from app.schemas.study import StudySpec


def done(draft: StudySpec | None) -> bool:
    return draft is not None and any(f.role == "outcome" for f in draft.features)


STAGE = Stage(
    id="outcome",
    title="Outcome",
    goal="Fix the outcome: source, filters, follow-up window and measure.",
    instructions=(
        "Use exactly one outcome with an outcome aggregation. Default to a 12-month "
        "follow-up and say so. If the measure is open (number of visits, any visit, "
        "time to first visit), ask with those as options."
    ),
    done=done,
)
