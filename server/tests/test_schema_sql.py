"""Static checks on db/schema.sql.

These run without a database: they parse the SQL and assert the properties that made an
earlier version unsafe to apply to the live project.

Background: an earlier draft declared ``appliances.user_id`` and scoped every RLS policy
to it. The live project (created from Member B's SQL) has ``household_id`` instead, so
re-running that draft failed with ``column "user_id" does not exist``. The extra tables
(``households``, ``tariff_plans``) also did not exist live.

``tools/check_schema_match.py`` compares the file against a real project; these tests
guard the parts that can be checked offline, so CI catches a regression immediately.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.store import APPLIANCE_FIELDS

SERVER = Path(__file__).resolve().parent.parent
SCHEMA = SERVER / "db" / "schema.sql"
OPTIONAL = SERVER / "db" / "optional-tariff-plans.sql"


def sql() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def without_comments() -> str:
    return "\n".join(
        (line.split("--")[0] if "--" in line else line) for line in sql().splitlines()
    )


def table_columns(table: str) -> set[str]:
    body = re.search(
        rf"create table if not exists public\.{table}\s*\((.*?)\n\);",
        without_comments(),
        re.S | re.I,
    )
    assert body, f"{table} table not found in schema.sql"

    columns: set[str] = set()
    for raw in body.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith(
            ("constraint", "primary key", "unique", "foreign key", "check", "or ", "and ")
        ):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0].lower()
        if re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            columns.add(name)
    return columns


class TestSchemaMatchesTheApi:
    def test_appliances_has_every_api_field(self):
        """The adapter writes these columns; the table must have all of them."""

        columns = table_columns("appliances")
        missing = [f for f in APPLIANCE_FIELDS if f not in columns]
        assert missing == [], f"appliances is missing API columns: {missing}"

    def test_appliances_has_household_scoping_column(self):
        assert "household_id" in table_columns("appliances")

    def test_profiles_has_the_columns_the_trigger_writes(self):
        columns = table_columns("profiles")
        assert {"id", "email", "full_name"} <= columns


class TestNoLeftoversFromTheOldDesign:
    def test_no_user_id_column(self):
        """The live table has no user_id; declaring one made the file unsafe to re-run."""

        assert "user_id" not in table_columns("appliances")
        body = without_comments().lower()
        assert "user_id" not in body, "schema.sql still mentions user_id outside comments"

    def test_no_households_table(self):
        assert not re.search(
            r"create table if not exists public\.households", without_comments(), re.I
        )

    def test_no_tariff_plans_table_in_the_main_schema(self):
        """Prices are data the calculators own; the mirror is optional and separate."""

        assert not re.search(
            r"create table if not exists public\.tariff_plans", without_comments(), re.I
        )
        assert OPTIONAL.exists(), "optional-tariff-plans.sql should exist"


class TestIdempotentAndSafe:
    @pytest.mark.parametrize(
        "statement",
        [
            "create table if not exists public.profiles",
            "create table if not exists public.appliances",
            "drop trigger if exists",
            "create index if not exists",
        ],
    )
    def test_uses_idempotent_guard(self, statement: str):
        assert statement in without_comments().lower()

    def test_every_policy_is_dropped_before_creation(self):
        """Re-running must not fail with 'policy already exists'."""

        body = without_comments().lower()
        created = re.findall(r"create policy\s+\"?([a-z_]+)", body)
        dropped = set(re.findall(r"drop policy if exists\s+\"?([a-z_]+)", body))
        assert created, "no policies found"
        missing = [name for name in created if name not in dropped]
        assert missing == [], f"policies created without a matching drop: {missing}"

    def test_rls_is_enabled_on_both_tables(self):
        body = without_comments().lower()
        assert "alter table public.profiles   enable row level security" in body or (
            "alter table public.profiles enable row level security" in body
        )
        assert "alter table public.appliances enable row level security" in body

    def test_policies_are_scoped_to_the_household(self):
        body = without_comments().lower()
        assert body.count("household_id = (select auth.uid())") >= 4


class TestOptionalFile:
    def test_tariff_plans_lives_in_the_optional_file(self):
        text = OPTIONAL.read_text(encoding="utf-8")
        assert re.search(r"create table if not exists public\.tariff_plans", text, re.I)

    def test_optional_file_is_idempotent(self):
        text = OPTIONAL.read_text(encoding="utf-8").lower()
        assert "if not exists" in text
        assert "on conflict (id) do update" in text
