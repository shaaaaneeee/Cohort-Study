"""What one stage of the assistant's conversation is.

The assistant walks a study through the stages in order (see __init__.py).
Each stage is its own file: what it settles, how the assistant handles it,
and when it counts as done for a draft study.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.schemas.study import StudySpec


@dataclass(frozen=True)
class Stage:
    id: str
    title: str
    # What the stage settles, shown to the model in the system prompt.
    goal: str
    # How the model handles the stage: what to settle itself, what to ask.
    instructions: str
    # True when a draft study has what this stage settles.
    done: Callable[[StudySpec | None], bool]
