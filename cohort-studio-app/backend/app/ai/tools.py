"""The tools the study assistant's model can call.

The JSON schemas are the same as the POC's, so a model prompt or script
written for it works unchanged. propose_study's schema is the StudySpec
schema itself, so the model is held to exactly the format the builder uses.

    propose_study       submit a whole study; answered with its design issues
    list_values         the values of one dimension, when the prompt lists only some
    ask_user            end the turn with questions for the user, each with clickable options
    report_unsupported  end the turn saying the data cannot answer the question
"""

from typing import Any

from app.ai.stages import STAGE_IDS
from app.schemas.study import StudySpec

TOOLS: list[dict[str, Any]] = [
    {
        "name": "propose_study",
        "description": (
            "Submit the complete study definition. The reply lists design issues found by the "
            "validator. If any has level 'error' the study was not accepted: fix it and call "
            "this tool again. Warnings are shown to the user next to the result. Always submit "
            "the whole study, not just the part that changed."
        ),
        "input_schema": StudySpec.model_json_schema(by_alias=True),
    },
    {
        "name": "list_values",
        "description": "All values of one dimension. Use source 'person' for person attributes.",
        "input_schema": {
            "type": "object",
            "properties": {"source": {"type": "string"}, "dimension": {"type": "string"}},
            "required": ["source", "dimension"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_user",
        "description": (
            "End your turn by asking the user the questions needed to complete the study. "
            "Ask only what you cannot reasonably settle yourself, at most four questions. "
            "Where the answer is a choice, give 2 to 5 short options the user can click, "
            "suggested default first, each a complete answer on its own (for example "
            "'ED attendances in the 12 months after'). The user can always type something "
            "else, so do not add an 'other' option."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 2,
                                "maxItems": 5,
                            },
                        },
                        "required": ["question"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                    "maxItems": 4,
                },
                "stage": {
                    "type": "string",
                    "enum": STAGE_IDS,
                    "description": "The stage the questions are about.",
                },
            },
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
    {
        "name": "report_unsupported",
        "description": (
            "End your turn when the question needs data, a comparison or an analysis this "
            "dataset does not have. Say what is missing and, if there is one, the closest "
            "study that is possible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = [t["name"] for t in TOOLS]
