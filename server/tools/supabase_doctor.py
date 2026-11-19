"""Check a Supabase project before pointing the app at it.

Answers the questions that decide whether the app can read your data:

1. does the project URL resolve and answer?
2. does the key work?
3. does the ``appliances`` table exist, and with which column layout?
4. how many rows are there, and can this key read them?
5. (optional) can this key *write*?

Setup (PowerShell)::

    $env:VOLTSPACE_SUPABASE_URL = "https://<project>.supabase.co"
    $env:VOLTSPACE_SUPABASE_KEY = "<anon or service_role key>"
    python tools/supabase_doctor.py

Add ``--write-test`` to also insert and delete a throwaway row.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

SERVER_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_ROOT))

from app.store import StoreError  # noqa: E402
from app.store_supabase import SupabaseStore  # noqa: E402
from app.storage import (  # noqa: E402
    SUPABASE_KEY,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    supabase_settings,
)

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


def line(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-test", action="store_true", help="also try insert+delete")
    args = parser.parse_args()

    print("=== VoltSpace Supabase doctor ===\n")

    try:
        settings = supabase_settings()
    except StoreError as exc:
        line(FAIL, "configuration", str(exc))
        return 1

    if settings is None:
        line(WARN, "not configured")
        print(f"\n  set {SUPABASE_URL} and {SUPABASE_KEY} (or {SUPABASE_SERVICE_KEY})")
        print("  the app will use local SQLite until you do")
        return 0

    url = settings["url"]
    host = urlparse(url).hostname or ""
    line(PASS, "project URL read", url)
    print(f"       key from: {SUPABASE_SERVICE_KEY if os.environ.get(SUPABASE_SERVICE_KEY) else SUPABASE_KEY}")

    # 1. DNS — a deleted or paused-away project stops resolving entirely.
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
        line(PASS, "DNS resolves", ", ".join(sorted(addresses))[:60])
    except OSError as exc:
        line(FAIL, "DNS does not resolve", f"{host}: {exc}")
        print(
            "\n  A Supabase project that has been deleted (or left inactive long enough)\n"
            "  removes its DNS record, so nothing can connect. Create a new project at\n"
            "  https://supabase.com/dashboard and point the variables at it."
        )
        return 1

    store = SupabaseStore(**settings)

    # 2. Can we read at all?
    try:
        count = store.count()
        line(PASS, "key can read the appliances table", f"{count} row(s)")
    except StoreError as exc:
        line(FAIL, "cannot read the appliances table", str(exc))
        return 1

    # 3. Which column layout does it have?
    try:
        layout = store.layout()
    except StoreError as exc:
        line(FAIL, "column layout", str(exc))
        return 1

    if layout == "current":
        line(PASS, "column layout", "current (power_watts / hours_per_day)")
    else:
        line(
            WARN,
            "column layout",
            "legacy (appliance / power / minutes) — days_per_month, voltage and "
            "power_factor are not stored",
        )
        print("       running db/schema.sql on a fresh project gives the full contract")

    # 4. Show a sample, without dumping everything.
    try:
        rows = store.list_appliances()
    except StoreError as exc:
        line(FAIL, "cannot list rows", str(exc))
        return 1

    if not rows:
        line(WARN, "table is empty", "the app will start with an empty household")
    else:
        print(f"\n  first {min(3, len(rows))} row(s) as the API sees them:")
        for row in rows[:3]:
            print(
                f"    #{row['id']} {row['name']}  "
                f"{row['power_watts']} W, {row['hours_per_day']} h/day, "
                f"qty {row['quantity']}"
            )

    # 5. Optional write test.
    if args.write_test:
        sample = {
            "name": "doctor-test",
            "power_watts": 123,
            "hours_per_day": 1,
            "days_per_month": 30,
            "quantity": 1,
        }
        try:
            created = store.add_appliance(sample)
        except StoreError as exc:
            line(FAIL, "key cannot write", str(exc))
            return 1
        line(PASS, "key can write", f"inserted id {created['id']}")
        try:
            store.delete_appliance(created["id"])
            line(PASS, "key can delete", f"removed id {created['id']}")
        except StoreError as exc:
            line(WARN, "inserted row could not be deleted", str(exc))
            print(f"       clean it up manually: id {created['id']}")
            return 1

    print("\n=== result ===")
    print("all checks passed — start the app with this environment set:")
    print(f"  storage: supabase ({url})")
    print("  /health should report \"storage\": \"supabase\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
