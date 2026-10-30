"""What a study can use, from the mapping config."""

from typing import Any, get_args

from app.core.mapping import Mapping
from app.schemas.study import AGGREGATIONS, FeatureSpec, Periodise, Window


def catalogue(mapping: Mapping) -> dict[str, Any]:
    """Everything a study can use, from the mapping config.

    Served to the builder as /api/metadata and written into the assistant's
    prompt. Physical table and column names other than dimensions and
    measures are left out: neither has any use for them.
    """
    sources = []
    for name, source in mapping.feature_sources().items():
        dimensions = [
            {"name": column, "label": dimension.label}
            for column, dimension in source.dimensions.items()
        ]
        measures = [
            {"name": column, "label": measure.label, "aggregations": measure.agg}
            for column, measure in source.measures.items()
        ]
        sources.append(
            {
                "name": name,
                "label": source.label or name,
                "granularity": source.granularity,
                "coverage": {"start": source.coverage.start, "end": source.coverage.end},
                "dimensions": dimensions,
                "measures": measures,
            }
        )
    return {
        "dataset": mapping.dataset,
        "exposures": [{"name": x.name, "label": x.label or x.name} for x in mapping.exposure],
        "person_attributes": mapping.person.attributes,
        "person_covariates": ["age", *mapping.person.attributes],
        "sources": sources,
        "aggregations": [
            {"name": name, "description": description} for name, description in AGGREGATIONS.items()
        ],
        "roles": list(get_args(FeatureSpec.model_fields["role"].annotation)),
        "window_units": list(get_args(Window.model_fields["unit"].annotation)),
        "period_grains": list(get_args(Periodise.model_fields["grain"].annotation)),
    }
