"""S4 Review: the study is checked against the data and handed to the builder.

The study is tried on the data before it is accepted (see
StudyService.feasibility). Done when the turn ends "ready".
"""

from app.ai.stages.base import Stage
from app.schemas.study import StudySpec


def done(draft: StudySpec | None) -> bool:
    # Reaching review needs every earlier stage; the turn's status decides the rest.
    return draft is not None


STAGE = Stage(
    id="review",
    title="Review",
    goal="Check the study can run on this data and hand it to the user.",
    instructions=(
        "Submit the study with propose_study. If it cannot run, say why in plain words "
        "and offer changes that could work. Once accepted, summarise it briefly with "
        "the defaults you chose, and ask the user to review it in the builder."
    ),
    done=done,
)
