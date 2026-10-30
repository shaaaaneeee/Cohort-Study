"""Write the API's OpenAPI document, from which the frontend's types are generated.

    python scripts/export_openapi.py ../frontend/openapi.json

Needs no database: the document comes from the route and schema definitions.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings
from app.core.mapping import load_mapping
from app.main import create_app


class _NoDatabase:
    def __init__(self) -> None:
        self.mapping = load_mapping(Settings(_env_file=None).mapping_path)  # type: ignore[call-arg]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    settings = Settings(_env_file=None, log_level="WARNING", log_format="text")  # type: ignore[call-arg]
    app = create_app(settings, repository=_NoDatabase())  # type: ignore[arg-type]
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
