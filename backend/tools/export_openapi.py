"""Write the generated OpenAPI document to ``docs/openapi.json``.

Keeping a committed copy lets Member A diff the contract between commits and import it
into an API client without running the server.

Usage::

    python tools/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402  (path setup must run first)


def main() -> int:
    target = BACKEND_ROOT / "docs" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths = ", ".join(sorted(schema["paths"]))
    print(f"wrote {target}")
    print(f"title   : {schema['info']['title']}")
    print(f"version : {schema['info']['version']}")
    print(f"paths   : {paths}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
