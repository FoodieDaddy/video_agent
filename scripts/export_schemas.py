"""Export JSON Schemas for the agent I/O contracts into ``config/schemas``.

The files are generated from the Pydantic models so there is a single source of
truth; prompt/schema drift is caught by tests.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
from studio_ai_runtime.schema_registry import export_schemas  # noqa: E402
from studio_api.bootstrap.schema_catalog import register_schemas  # noqa: E402


def main() -> int:
    register_schemas()
    target = REPO_ROOT / "config" / "schemas"
    written = export_schemas(target)
    for path in written:
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(f"{path.relative_to(REPO_ROOT)}: {payload.get('title', '')}")
    print(f"exported {len(written)} schema files to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
