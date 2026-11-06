"""The stages the assistant takes a study through, in order.

    S0 question -> S1 cohort -> S2 covariates -> S3 outcome -> S4 review

It is one model with one conversation, not a model per stage: every stage's
instructions are in the system prompt, and the model settles as many stages
as the question allows in one turn. A complete question goes straight to
review; a vague one is asked about one stage at a time. The stage reported
to the page (for its progress bar) is the one the model asked about, or else
the first stage the draft has not finished.
"""

from app.ai.stages import s0_question, s1_cohort, s2_covariates, s3_outcome, s4_review
from app.ai.stages.base import Stage
from app.schemas.study import StudySpec

STAGES: list[Stage] = [
    s0_question.STAGE,
    s1_cohort.STAGE,
    s2_covariates.STAGE,
    s3_outcome.STAGE,
    s4_review.STAGE,
]
STAGE_IDS = [s.id for s in STAGES]


def current_stage(draft: StudySpec | None, status: str, asked: str | None = None) -> dict:
    """The stage a turn ended in, as {id, number, title, total} for the page.

    asked is the stage the model said its questions were about, if any.
    """
    if status == "ready":
        stage = STAGES[-1]
    elif asked in STAGE_IDS:
        stage = STAGES[STAGE_IDS.index(asked)]
    else:
        stage = next((s for s in STAGES if not s.done(draft)), STAGES[-1])
    return {
        "id": stage.id,
        "number": STAGES.index(stage),
        "title": stage.title,
        "total": len(STAGES),
    }


def prompt_section() -> str:
    """The stages as written into the system prompt."""
    lines = [
        "Work through these stages in order. Settle every stage the question already "
        "answers in one go; if a stage is left open in a way that changes the study, "
        "stop there and ask about that stage only (set ask_user's stage), then continue "
        "from it on the next turn. A complete question goes straight to S4."
    ]
    for number, stage in enumerate(STAGES):
        lines.append(f"S{number} {stage.title} ({stage.id}): {stage.goal}\n  {stage.instructions}")
    return "\n".join(lines)
