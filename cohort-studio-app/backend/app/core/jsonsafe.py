"""Make results safe to send as JSON."""

import math


def clean(value: object) -> object:
    """Replace NaN and infinity, which JSON cannot carry, with None, all the way down."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value
