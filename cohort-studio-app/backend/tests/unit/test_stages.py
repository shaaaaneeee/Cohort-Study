from app.ai.stages import STAGES, current_stage, prompt_section
from app.schemas.study import StudySpec

OUTCOME = {
    "name": "ed_post",
    "label": "ED attendances, 12 months after",
    "source": "ed_episodes",
    "window": {"from": 1, "to": 12, "unit": "months"},
    "aggregation": "count",
    "role": "outcome",
}


def study(**extra) -> StudySpec:
    return StudySpec.model_validate({"exposure": "program_a", **extra})


def test_the_stages_run_s0_to_s4_in_order():
    assert [s.id for s in STAGES] == ["question", "cohort", "covariates", "outcome", "review"]


def test_no_draft_is_the_question_stage():
    assert current_stage(None, "asking")["id"] == "question"


def test_a_draft_without_covariates_is_at_covariates():
    assert current_stage(study(), "asking") == {
        "id": "covariates",
        "number": 2,
        "title": "Covariates",
        "total": 5,
    }


def test_a_draft_without_an_outcome_is_at_outcome():
    assert current_stage(study(person_covariates=["age"]), "asking")["id"] == "outcome"


def test_a_ready_study_is_at_review():
    draft = study(person_covariates=["age"], features=[OUTCOME])
    assert current_stage(draft, "ready")["id"] == "review"


def test_the_stage_asked_about_wins():
    assert current_stage(None, "asking", asked="outcome")["id"] == "outcome"
    assert current_stage(None, "asking", asked="nonsense")["id"] == "question"


def test_every_stage_is_in_the_prompt():
    text = prompt_section()
    for number, stage in enumerate(STAGES):
        assert f"S{number} {stage.title}" in text
