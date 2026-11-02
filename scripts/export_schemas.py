"""Export JSON Schemas for the agent I/O contracts into ``config/schemas``.

The files are generated from the Pydantic models so there is a single source of
truth; prompt/schema drift is caught by tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.schemas.registry import export_schemas  # noqa: E402


def main() -> int:
    target = REPO_ROOT / "config" / "schemas"
    written = export_schemas(target)
    for path in written:
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(f"{path.relative_to(REPO_ROOT)}: {payload.get('title', '')}")
    print(f"exported {len(written)} schema files to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
