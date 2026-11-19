"""Tests for the Supabase store adapter.

Network-free: a small in-memory stand-in for PostgREST answers the HTTP calls through
``httpx.MockTransport``. That exercises the real request/response path (URL building,
headers, column mapping, error translation) without needing a project or a key.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.store import StoreError
from app.store_supabase import CURRENT_LAYOUT, LEGACY_LAYOUT, SupabaseStore
from app.storage import create_store, supabase_settings

# --------------------------------------------------------------------------- fake


class FakePostgrest:
    """A miniature PostgREST: enough of the query language for this adapter."""

    def __init__(self, layout: str = "current") -> None:
        self.layout = layout
        self.rows: list[dict[str, Any]] = []
        self.next_id = 1
        self.requests: list[tuple[str, str]] = []
        self.force_status: tuple[int, dict[str, Any]] | None = None

    # -- which columns the fake table has --
    @property
    def columns(self) -> list[str]:
        if self.layout == "current":
            return ["id", *CURRENT_LAYOUT.values(), "household_id"]
        if self.layout == "legacy":
            return ["id", "appliance", "power", "quantity", "minutes"]
        return ["id"]  # "neither": both layout probes must fail

    def _parse_select(self, select: str) -> None:
        """Raise like PostgREST when a probe names a column that does not exist."""

        if select in ("*", ""):
            return
        for name in select.split(","):
            name = name.strip()
            if name and name not in self.columns:
                raise _PostgrestError(
                    400,
                    {"code": "42703", "message": f"column {name} does not exist"},
                )

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        params = request.url.params
        self.requests.append((method, str(request.url)))

        if self.force_status:
            status, body = self.force_status
            return httpx.Response(status, json=body)

        try:
            self._parse_select(params.get("select", "*"))
        except _PostgrestError as exc:
            return httpx.Response(exc.status, json=exc.body)

        rows = list(self.rows)

        # filters. PostgREST supports more operators than `eq`; the adapter needs `gte`
        # for its explicit "match everything" delete filter.
        saw_filter = False
        for key, value in params.multi_items():
            if key in {"select", "order", "limit"}:
                continue
            saw_filter = True
            if value.startswith("eq."):
                target = value[3:]
                rows = [row for row in rows if str(row.get(key)) == str(target)]
            elif value.startswith("gte."):
                floor = float(value[4:])
                rows = [row for row in rows if float(row.get(key, 0)) >= floor]
            elif value.startswith("neq."):
                target = value[4:]
                rows = [row for row in rows if str(row.get(key)) != str(target)]

        # Faithful to the real server: an unfiltered DELETE is rejected with 21000.
        if method == "DELETE" and not saw_filter:
            return httpx.Response(
                400,
                json={
                    "code": "21000",
                    "message": "DELETE requires a WHERE clause",
                },
            )

        if params.get("order", "").startswith("id"):
            rows.sort(key=lambda row: row["id"])
        limit = params.get("limit")
        if limit:
            rows = rows[: int(limit)]

        if method == "GET":
            return httpx.Response(200, json=rows)

        if method == "POST":
            payload = json.loads(request.content.decode())
            items = payload if isinstance(payload, list) else [payload]

            if self.layout == "current":
                for row in items:
                    if row.get("household_id") and "household_id" not in self.columns:
                        return httpx.Response(
                            400, json={"code": "42703", "message": "column household_id"}
                        )
            stored = []
            for item in items:
                row = dict(item)
                row["id"] = self.next_id
                self.next_id += 1
                self.rows.append(row)
                stored.append(row)
            return httpx.Response(201, json=stored)

        if method == "PATCH":
            changes = json.loads(request.content.decode())
            updated = []
            for row in rows:
                row.update(changes)
                updated.append(row)
            return httpx.Response(200, json=updated)

        if method == "DELETE":
            removed = [row for row in self.rows if row in rows]
            self.rows = [row for row in self.rows if row not in rows]
            return httpx.Response(200, json=removed)

        return httpx.Response(405, json={"message": "method not allowed"})


class _PostgrestError(Exception):
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body
        super().__init__(body.get("message", ""))


def make_store(fake: FakePostgrest, **kwargs: Any) -> SupabaseStore:
    return SupabaseStore(
        "https://demo.supabase.co",
        "test-key",
        transport=httpx.MockTransport(fake.handler),
        **kwargs,
    )


AC = {
    "name": "冷氣機",
    "category": "cooling",
    "power_watts": 900,
    "hours_per_day": 6,
    "days_per_month": 30,
    "quantity": 1,
    "voltage": 220,
    "power_factor": 0.9,
}

# --------------------------------------------------------------------- layout


class TestLayoutDetection:
    def test_detects_the_current_layout(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        assert store.layout() == "current"

    def test_detects_member_b_legacy_layout(self):
        fake = FakePostgrest("legacy")
        store = make_store(fake)
        assert store.layout() == "legacy"

    def test_layout_is_cached(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        store.layout()
        before = len(fake.requests)
        store.layout()
        store.layout()
        assert len(fake.requests) == before, "the probe should run once"

    def test_unknown_layout_explains_both_attempts(self):
        fake = FakePostgrest("neither")
        store = make_store(fake)
        with pytest.raises(StoreError) as excinfo:
            store.layout()
        assert "column layout" in str(excinfo.value) or "could not read" in str(excinfo.value)


# ------------------------------------------------------------------ mapping


class TestCurrentLayoutMapping:
    def test_add_returns_api_shape(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        row = store.add_appliance(AC)

        assert row["id"] == 1
        assert row["name"] == "冷氣機"
        assert row["power_watts"] == 900.0
        assert row["hours_per_day"] == 6.0
        assert row["days_per_month"] == 30
        assert row["voltage"] == 220.0
        assert row["power_factor"] == 0.9

    def test_list_returns_rows_in_id_order(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        store.add_appliance(AC)
        store.add_appliance({**AC, "name": "冰箱", "power_watts": 130})
        rows = store.list_appliances()
        assert [row["name"] for row in rows] == ["冷氣機", "冰箱"]
        assert [row["id"] for row in rows] == [1, 2]

    def test_count(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        assert store.count() == 0
        store.add_appliance(AC)
        assert store.count() == 1

    def test_get_missing_returns_none(self):
        store = make_store(FakePostgrest("current"))
        assert store.get_appliance(999) is None

    def test_update_merges_partial_changes(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        created = store.add_appliance(AC)

        updated = store.update_appliance(created["id"], {"hours_per_day": 2})
        assert updated is not None
        assert updated["hours_per_day"] == 2.0
        assert updated["name"] == "冷氣機", "other fields must be preserved"
        assert updated["power_watts"] == 900.0

    def test_update_missing_returns_none(self):
        store = make_store(FakePostgrest("current"))
        assert store.update_appliance(404, {"hours_per_day": 1}) is None

    def test_delete(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        created = store.add_appliance(AC)
        assert store.delete_appliance(created["id"]) is True
        assert store.delete_appliance(created["id"]) is False
        assert store.count() == 0

    def test_replace_overwrites_everything(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        store.add_appliance(AC)
        store.add_appliance({**AC, "name": "冰箱"})

        rows = store.replace_appliances([{**AC, "name": "除濕機", "power_watts": 150}])
        assert [row["name"] for row in rows] == ["除濕機"]
        assert store.count() == 1

    def test_replace_with_empty_list_clears(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        store.add_appliance(AC)
        assert store.replace_appliances([]) == []
        assert store.count() == 0

    def test_clear(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        store.add_appliance(AC)
        store.clear()
        assert store.count() == 0


class TestLegacyLayoutMapping:
    def test_reads_minutes_as_hours(self):
        fake = FakePostgrest("legacy")
        # 360 minutes per day == 6 hours.
        fake.rows.append(
            {"id": 1, "appliance": "冷氣機", "power": 900, "quantity": 1, "minutes": 360}
        )
        store = make_store(fake)
        row = store.list_appliances()[0]
        assert row["hours_per_day"] == 6.0
        assert row["power_watts"] == 900.0
        assert row["name"] == "冷氣機"
        assert row["days_per_month"] == 30, "the legacy table has no days column"
        assert row["voltage"] is None

    def test_writes_minutes_not_hours(self):
        fake = FakePostgrest("legacy")
        store = make_store(fake)
        store.add_appliance(AC)
        stored = fake.rows[0]
        assert stored["minutes"] == 360.0, "6 hours must be stored as 360 minutes"
        assert stored["power"] == 900
        assert stored["appliance"] == "冷氣機"
        assert "hours_per_day" not in stored

    def test_round_trip_preserves_usage(self):
        fake = FakePostgrest("legacy")
        store = make_store(fake)
        created = store.add_appliance(AC)
        assert created["hours_per_day"] == 6.0


class TestNumericCoercion:
    def test_numeric_strings_from_postgres_become_floats(self):
        """numeric/decimal columns come back as strings in some PostgREST setups."""

        fake = FakePostgrest("current")
        fake.rows.append(
            {
                "id": 7,
                "name": "冰箱",
                "category": None,
                "power_watts": "130.00",
                "hours_per_day": "24.00",
                "days_per_month": "30",
                "quantity": "1",
                "voltage": "110.00",
                "power_factor": None,
            }
        )
        store = make_store(fake)
        row = store.list_appliances()[0]
        assert row["power_watts"] == 130.0
        assert row["hours_per_day"] == 24.0
        assert row["days_per_month"] == 30
        assert row["quantity"] == 1


# ------------------------------------------------------------------ scoping


class TestHouseholdScoping:
    def test_rows_are_filtered_by_household_id(self):
        fake = FakePostgrest("current")
        store = make_store(fake, household_id="11111111-1111-1111-1111-111111111111")
        store.add_appliance(AC)
        assert fake.rows[0]["household_id"] == "11111111-1111-1111-1111-111111111111"

        fake.rows.append(
            {**fake.rows[0], "id": 99, "household_id": "22222222-2222-2222-2222-222222222222"}
        )
        rows = store.list_appliances()
        assert [row["id"] for row in rows] == [1], "other households must not leak"

    def test_no_scope_when_not_configured(self):
        fake = FakePostgrest("current")
        store = make_store(fake)
        store.add_appliance(AC)
        assert "household_id" not in fake.rows[0]


# ------------------------------------------------------------------- errors


class TestErrorTranslation:
    def test_rls_violation_suggests_the_service_key(self):
        fake = FakePostgrest("current")
        fake.force_status = (
            401,
            {"code": "42501", "message": "new row violates row-level security policy"},
        )
        store = make_store(fake)
        with pytest.raises(StoreError) as excinfo:
            store.count()
        message = str(excinfo.value)
        assert "service_role" in message
        assert "row level security" in message

    def test_missing_table_suggests_the_schema(self):
        fake = FakePostgrest("current")
        fake.force_status = (
            404,
            {"code": "42P01", "message": 'relation "public.appliances" does not exist'},
        )
        store = make_store(fake)
        with pytest.raises(StoreError) as excinfo:
            store.count()
        assert "schema.sql" in str(excinfo.value)

    def test_undefined_column_is_explained(self):
        fake = FakePostgrest("current")
        fake.force_status = (
            400,
            {"code": "42703", "message": "column appliances.power_watts does not exist"},
        )
        store = make_store(fake)
        with pytest.raises(StoreError) as excinfo:
            store.count()
        assert "column layout" in str(excinfo.value)

    def test_network_failure_is_a_store_error(self):
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("name resolution failed")

        store = SupabaseStore(
            "https://gone.supabase.co", "key", transport=httpx.MockTransport(boom)
        )
        with pytest.raises(StoreError) as excinfo:
            store.count()
        message = str(excinfo.value)
        assert "cannot reach Supabase" in message
        assert "paused" in message

    def test_non_json_error_body_is_handled(self):
        fake = FakePostgrest("current")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(502, text="<html>bad gateway</html>")
            return fake.handler(request)

        store = SupabaseStore(
            "https://demo.supabase.co", "key", transport=httpx.MockTransport(handler)
        )
        with pytest.raises(StoreError) as excinfo:
            store.count()
        assert "HTTP 502" in str(excinfo.value)


# ------------------------------------------------------- configuration


class TestConfiguration:
    def test_settings_are_none_when_unset(self, monkeypatch):
        for name in (
            "VOLTSPACE_SUPABASE_URL",
            "VOLTSPACE_SUPABASE_KEY",
            "VOLTSPACE_SUPABASE_SERVICE_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        assert supabase_settings() is None

    def test_settings_read_url_and_key(self, monkeypatch):
        monkeypatch.setenv("VOLTSPACE_SUPABASE_URL", "https://x.supabase.co/")
        monkeypatch.setenv("VOLTSPACE_SUPABASE_KEY", "abc")
        # The service key wins when present, so clear it - otherwise this test would
        # read whatever the developer happens to have exported in their shell.
        monkeypatch.delenv("VOLTSPACE_SUPABASE_SERVICE_KEY", raising=False)
        settings = supabase_settings()
        assert settings == {
            "url": "https://x.supabase.co/",
            "key": "abc",
            "table": "appliances",
            "household_id": None,
        }

    def test_service_key_wins_over_the_plain_key(self, monkeypatch):
        monkeypatch.setenv("VOLTSPACE_SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("VOLTSPACE_SUPABASE_KEY", "anon")
        monkeypatch.setenv("VOLTSPACE_SUPABASE_SERVICE_KEY", "service")
        assert supabase_settings()["key"] == "service"

    def test_half_configuration_is_an_error(self, monkeypatch):
        monkeypatch.setenv("VOLTSPACE_SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.delenv("VOLTSPACE_SUPABASE_KEY", raising=False)
        monkeypatch.delenv("VOLTSPACE_SUPABASE_SERVICE_KEY", raising=False)
        with pytest.raises(StoreError) as excinfo:
            supabase_settings()
        assert "partly configured" in str(excinfo.value)


class TestCreateStore:
    def test_no_configuration_uses_sqlite(self, monkeypatch):
        for name in (
            "VOLTSPACE_SUPABASE_URL",
            "VOLTSPACE_SUPABASE_KEY",
            "VOLTSPACE_SUPABASE_SERVICE_KEY",
            "VOLTSPACE_STORAGE",
        ):
            monkeypatch.delenv(name, raising=False)
        store = create_store()
        assert type(store).__name__ == "ApplianceStore"

    def test_mode_local_ignores_supabase(self, monkeypatch):
        monkeypatch.setenv("VOLTSPACE_STORAGE", "local")
        monkeypatch.setenv("VOLTSPACE_SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("VOLTSPACE_SUPABASE_KEY", "abc")
        store = create_store()
        assert type(store).__name__ == "ApplianceStore"

    def test_mode_supabase_without_configuration_fails(self, monkeypatch):
        monkeypatch.setenv("VOLTSPACE_STORAGE", "supabase")
        for name in (
            "VOLTSPACE_SUPABASE_URL",
            "VOLTSPACE_SUPABASE_KEY",
            "VOLTSPACE_SUPABASE_SERVICE_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(StoreError):
            create_store()

    def test_invalid_mode_fails(self, monkeypatch):
        monkeypatch.setenv("VOLTSPACE_STORAGE", "cloud")
        with pytest.raises(StoreError) as excinfo:
            create_store()
        assert "must be auto" in str(excinfo.value)
