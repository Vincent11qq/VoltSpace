"""Connectivity check for the Supabase project — Member B's original script, cleaned up.

SUPERSEDED: the backend stores data locally by default (``backend/app/store.py``);
see ``backend/docs/supabase.md`` to use Supabase instead.

What changed from the original:

* **The URL and key were hard-coded and committed.** They now come from environment
  variables, so no credential lives in the repository.
* **The original queried the database and printed results at import time**, which meant
  merely importing the module had side effects. All work now happens in ``main()``, so
  ``import Supabase`` is safe.

Run it as a script::

    set VOLTSPACE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
    set VOLTSPACE_SUPABASE_KEY=<publishable / anon key>
    python Supabase.py
"""

from __future__ import annotations

import os
import sys


def _client():
    url = os.environ.get("VOLTSPACE_SUPABASE_URL")
    key = os.environ.get("VOLTSPACE_SUPABASE_KEY")
    if not url or not key:
        print(
            "Supabase is not configured.\n"
            "  set VOLTSPACE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co\n"
            "  set VOLTSPACE_SUPABASE_KEY=<publishable / anon key>\n\n"
            "The app does not need Supabase: it stores data locally by default "
            "(backend/app/store.py).",
            file=sys.stderr,
        )
        return None

    from supabase import create_client

    return create_client(url, key)


def main() -> int:
    client = _client()
    if client is None:
        return 1

    for table in ("profiles", "appliances"):
        try:
            response = client.table(table).select("*").execute()
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"{table}: query failed -> {exc}")
            continue
        rows = response.data or []
        print(f"{table}: {len(rows)} row(s)")

    print("Database check finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
