"""Supabase (PostgREST) adapter for the household store.

Why this exists
---------------
``app/store.py`` keeps the household in a local SQLite file so the app runs with zero
setup. This module is the other half: the same interface, backed by Supabase, so the
data can be shared between devices.

It speaks PostgREST over HTTP with ``httpx``, which is already a dependency (FastAPI's
test client needs it). That deliberately avoids adding the ``supabase`` Python package:
no extra install step, and nothing new to break on a machine without pip.

Column layouts
--------------
Two layouts exist in this project's history, and this adapter reads **both**:

* current (``db/schema.sql``): ``name``, ``power_watts``, ``hours_per_day``,
  ``days_per_month``, ``quantity``, ``voltage``, ``power_factor``
* Member B's original: ``appliance``, ``power``, ``minutes``, ``quantity``

Postgres folds unquoted identifiers to lower case, so ``Appliance`` in the original SQL
is really the column ``appliance``. The layout is detected once, by probing ``select=``
against each candidate, and cached.

Known limits of the legacy layout
---------------------------------
It has no ``days_per_month``, ``voltage`` or ``power_factor`` column, so those values are
defaulted (30 / None / None) on read and **not persisted** on write. Run
``db/schema.sql`` against a fresh project to get the full contract.
"""

from __future__ import annotations

from typing import Any, Iterable

import httpx

from .store import APPLIANCE_FIELDS, StoreError, normalise_appliance

DEFAULT_TABLE = "appliances"

# PostgREST error codes worth translating into advice.
_RLS_VIOLATION = "42501"
_UNDEFINED_COLUMN = "42703"
_MISSING_TABLE = "42P01"

# --- column layouts ---------------------------------------------------------
# Maps the API field name onto the column that holds it in each layout.
CURRENT_LAYOUT: dict[str, str] = {field: field for field in APPLIANCE_FIELDS}
LEGACY_LAYOUT: dict[str, str] = {
    "name": "appliance",
    "category": None,          # absent
    "power_watts": "power",
    "hours_per_day": "minutes",  # minutes per day -> divided by 60 on read
    "days_per_month": None,      # absent, always 30
    "quantity": "quantity",
    "voltage": None,             # absent
    "power_factor": None,        # absent
}

# Columns probed to work out which layout a project uses.
_PROBES = {
    "current": "id,power_watts,hours_per_day",
    "legacy": "id,power,minutes",
}


class SupabaseStore:
    """A household store backed by a Supabase table over PostgREST.

    ``transport`` exists so the tests can drive it with ``httpx.MockTransport`` and never
    touch the network.
    """

    backend_name = "supabase"

    def __init__(
        self,
        url: str,
        key: str,
        *,
        table: str = DEFAULT_TABLE,
        household_id: str | None = None,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not url or not key:
            raise StoreError("Supabase needs both a project URL and an API key")
        self.url = url.rstrip("/")
        self.base = f"{self.url}/rest/v1"
        self.key = key
        self.table = table
        self.household_id = household_id
        self.timeout = timeout
        self._transport = transport
        self._layout: str | None = None

    # --- plumbing ----------------------------------------------------------
    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _endpoint(self) -> str:
        return f"{self.base}/{self.table}"

    def _scope(self) -> list[tuple[str, str]]:
        if self.household_id:
            return [("household_id", f"eq.{self.household_id}")]
        return []

    def _request(
        self,
        method: str,
        *,
        params: Iterable[tuple[str, str]] | None = None,
        body: Any = None,
        prefer: str | None = None,
    ) -> Any:
        """One PostgREST call. Raises ``StoreError`` with the server's own message."""

        headers = self._headers(prefer)
        if body is not None:
            headers["Content-Type"] = "application/json"

        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.request(
                    method,
                    self._endpoint(),
                    params=list(params or []),
                    json=body,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise StoreError(
                f"cannot reach Supabase at {self.url}: {exc}. "
                "Check the project URL and that the project is not paused."
            ) from exc

        if response.status_code >= 400:
            raise StoreError(self._explain(response))

        if not response.content:
            return None
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text

    @staticmethod
    def _explain(response: httpx.Response) -> str:
        """Turn a PostgREST error body into something actionable."""

        try:
            payload = response.json()
        except ValueError:
            return f"Supabase returned HTTP {response.status_code}: {response.text[:200]}"

        code = str(payload.get("code") or "")
        message = payload.get("message") or payload.get("error") or "unknown error"
        hint = payload.get("hint")

        if code == _RLS_VIOLATION:
            return (
                f"Supabase refused the request ({code}: {message}). The table's row level "
                "security is blocking this key. Use the service_role key in the backend "
                "(never in a client), or add a policy that allows this key. "
                "See docs/supabase.md."
            )
        # Column before table: PostgREST reports a missing column with code 42703 and a
        # "does not exist" message, which must not be mistaken for a missing table.
        if code == _UNDEFINED_COLUMN:
            return (
                f"Supabase has a different column layout than expected: {message}. "
                "Run db/schema.sql to align the columns, or use the legacy layout."
            )
        if code == _MISSING_TABLE or "relation" in str(message).lower():
            return (
                f"Supabase says: {message}. Run db/schema.sql in the Supabase SQL editor "
                f"to create the tables. Hint: {hint}"
                if hint
                else f"Supabase says: {message}. Run db/schema.sql in the Supabase SQL "
                "editor to create the tables."
            )
        detail = f" ({code})" if code else ""
        return f"Supabase error{detail}: {message}" + (f" — hint: {hint}" if hint else "")

    # --- layout detection --------------------------------------------------
    def layout(self) -> str:
        """'current' or 'legacy'. Detected once, by probing the columns."""

        if self._layout:
            return self._layout

        errors: list[str] = []
        for name, columns in _PROBES.items():
            try:
                self._request("GET", params=[("select", columns), ("limit", "1")])
            except StoreError as exc:
                errors.append(f"{name}: {exc}")
                continue
            self._layout = name
            return name

        raise StoreError(
            "could not read the Supabase appliances table with either column layout. "
            + " | ".join(errors)
        )

    def columns(self) -> dict[str, str]:
        return CURRENT_LAYOUT if self.layout() == "current" else LEGACY_LAYOUT

    # --- row <-> API mapping -----------------------------------------------
    def _row_to_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        """Map a database row onto the API's flat shape (the shape ``store.py`` uses)."""

        mapping = self.columns()
        out: dict[str, Any] = {"id": row.get("id")}

        for field, column in mapping.items():
            if column is None:
                if field == "days_per_month":
                    out[field] = 30
                else:
                    out[field] = None
                continue
            out[field] = row.get(column)

        # Legacy stores usage in minutes; the API and calculators use hours.
        if self.layout() == "legacy":
            minutes = out.get("hours_per_day")
            out["hours_per_day"] = (float(minutes) / 60.0) if minutes is not None else 0.0
            out["category"] = None
            out["days_per_month"] = 30
            out["voltage"] = None
            out["power_factor"] = None

        # Numbers arrive as strings from numeric/decimal columns.
        for field in ("power_watts", "hours_per_day", "voltage", "power_factor"):
            if out.get(field) is not None:
                out[field] = float(out[field])
        for field in ("days_per_month", "quantity"):
            if out.get(field) is not None:
                out[field] = int(out[field])
        return out

    def _dict_to_row(self, appliance: dict[str, Any]) -> dict[str, Any]:
        """Map an API-shaped appliance onto the columns this project actually has."""

        normalised = normalise_appliance(appliance)
        mapping = self.columns()
        payload: dict[str, Any] = {}

        for field, column in mapping.items():
            if column is None:
                continue
            value = normalised.get(field)
            if field == "hours_per_day" and self.layout() == "legacy":
                payload[column] = round(float(value) * 60.0, 2)
                continue
            if field == "power_watts" and self.layout() == "legacy":
                payload[column] = int(round(float(value)))
                continue
            payload[column] = value

        if self.household_id:
            payload["household_id"] = self.household_id
        return payload

    # --- reads -------------------------------------------------------------
    def list_appliances(self) -> list[dict[str, Any]]:
        rows = self._request(
            "GET", params=[*self._scope(), ("select", "*"), ("order", "id.asc")]
        )
        return [self._row_to_dict(row) for row in (rows or [])]

    def count(self) -> int:
        """Row count for the household.

        Fetches only the ``id`` column: PostgREST's ``Prefer: count=exact`` header variant
        would avoid even that, but it needs header access this wrapper does not expose,
        and a household is small.
        """

        rows = self._request("GET", params=[*self._scope(), ("select", "id")])
        return len(rows or [])

    def get_appliance(self, appliance_id: int) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            params=[*self._scope(), ("select", "*"), ("id", f"eq.{appliance_id}"), ("limit", "1")],
        )
        if not rows:
            return None
        return self._row_to_dict(rows[0])

    # --- writes ------------------------------------------------------------
    def add_appliance(self, appliance: dict[str, Any]) -> dict[str, Any]:
        payload = self._dict_to_row(appliance)
        rows = self._request(
            "POST", body=payload, prefer="return=representation"
        )
        if not rows:
            raise StoreError("Supabase accepted the insert but returned no row")
        return self._row_to_dict(rows[0])

    def update_appliance(
        self, appliance_id: int, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Merge ``changes`` into the stored row, then write the whole row back.

        A full-row write keeps one mapping path (``_dict_to_row``) instead of a second,
        partial-update one that could drift.
        """

        existing = self.get_appliance(appliance_id)
        if existing is None:
            return None

        body = self._dict_to_row({**existing, **changes})
        rows = self._request(
            "PATCH",
            params=[*self._scope(), ("id", f"eq.{appliance_id}")],
            body=body,
            prefer="return=representation",
        )
        if not rows:
            return None
        return self._row_to_dict(rows[0])

    def delete_appliance(self, appliance_id: int) -> bool:
        rows = self._request(
            "DELETE",
            params=[*self._scope(), ("id", f"eq.{appliance_id}")],
            prefer="return=representation",
        )
        return bool(rows)

    def replace_appliances(self, appliances: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Overwrite the household.

        PostgREST has no multi-statement transaction here, so an insert failure after the
        delete would leave the household empty. The caller should treat a ``StoreError``
        from this method as "the data may be partly written".
        """

        payload = [self._dict_to_row(appliance) for appliance in appliances]
        self._request("DELETE", params=self._scope(), prefer="return=minimal")
        if not payload:
            return []
        rows = self._request("POST", body=payload, prefer="return=representation")
        return [self._row_to_dict(row) for row in (rows or [])]

    def clear(self) -> None:
        self._request("DELETE", params=self._scope(), prefer="return=minimal")
