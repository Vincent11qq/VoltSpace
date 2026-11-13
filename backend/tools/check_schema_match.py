"""Verify db/schema.sql matches the live Supabase tables.

Reads the CREATE TABLE blocks out of schema.sql and compares each column against the
columns PostgREST reports for the live project. Also checks that no policy references a
column that does not exist (the bug this rewrite fixes).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")

URL = os.environ["VOLTSPACE_SUPABASE_URL"].rstrip("/")
KEY = os.environ.get("VOLTSPACE_SUPABASE_SERVICE_KEY") or os.environ["VOLTSPACE_SUPABASE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

SQL = (BACKEND / "db" / "schema.sql").read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    return "\n".join(
        line.split("--")[0] if "--" in line else line for line in text.splitlines()
    )


def columns_from_sql(table: str) -> set[str]:
    match = re.search(
        rf"create table if not exists public\.{table}\s*\((.*?)\n\);",
        strip_comments(SQL),
        re.S | re.I,
    )
    if not match:
        raise SystemExit(f"could not find the {table} table in schema.sql")
    body = match.group(1)

    columns: set[str] = set()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        # Skip table constraints and the continuation lines of a multi-line CHECK.
        if lowered.startswith(
            ("constraint", "primary key", "unique", "foreign key", "check", "or ", "and ")
        ):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0].lower()
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            continue
        columns.add(name)
    return columns


def live_columns(table: str) -> set[str]:
    spec = httpx.get(f"{URL}/rest/v1/", headers=HEADERS, timeout=20).json()
    properties = spec.get("definitions", {}).get(table, {}).get("properties", {})
    return set(properties)


def main() -> int:
    failures: list[str] = []

    for table in ("profiles", "appliances"):
        sql_cols = columns_from_sql(table)
        live = live_columns(table)

        missing_in_sql = sorted(live - sql_cols)
        extra_in_sql = sorted(sql_cols - live)

        print(f"\n{table}:")
        print(f"  schema.sql columns : {sorted(sql_cols)}")
        print(f"  live columns       : {sorted(live)}")

        if missing_in_sql:
            print(f"  [FAIL] live has these but schema.sql does not: {missing_in_sql}")
            failures.append(f"{table}: schema.sql missing {missing_in_sql}")
        else:
            print("  [PASS] every live column is declared in schema.sql")

        if extra_in_sql:
            print(f"  [WARN] schema.sql declares columns the live table lacks: {extra_in_sql}")
            print("         (fine for a fresh install, but the live table will not have them)")
        else:
            print("  [PASS] no extra columns")

    # The regression this rewrite fixes: policies must not mention user_id.
    print("\npolicy references:")
    body = strip_comments(SQL)
    policies = re.findall(r"create policy[\s\S]*?;", body, re.I)
    offenders = [p.splitlines()[0].strip() for p in policies if "user_id" in p.lower()]
    if offenders:
        print(f"  [FAIL] policies still reference user_id: {offenders}")
        failures.append("policies reference user_id, which the live table does not have")
    else:
        print(f"  [PASS] {len(policies)} policies, none reference user_id")

    print("\nhouseholds table:")
    if re.search(r"create table if not exists public\.households", SQL, re.I):
        print("  [FAIL] schema.sql still creates households (live project has none)")
        failures.append("schema.sql creates a households table that does not exist live")
    else:
        print("  [PASS] not created (matches the live project)")

    print("\ntariff_plans:")
    if re.search(r"create table if not exists public\.tariff_plans", SQL, re.I):
        print("  [WARN] tariff_plans is in schema.sql; move it to optional-tariff-plans.sql")
    else:
        print("  [PASS] kept out of the main schema (moved to optional-tariff-plans.sql)")

    print()
    if failures:
        print(f"{len(failures)} problem(s)")
        for item in failures:
            print("  -", item)
        return 1
    print("schema.sql matches the live database")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
