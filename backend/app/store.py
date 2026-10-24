"""A tiny SQLite store for the user's saved appliances.

Why this exists
---------------
VoltSpace's calculation API is stateless: the frontend sends the whole appliance list
with every request. That is perfect for the calculation core, but a real app needs the
list to *persist* between visits.

Member B built a Supabase schema for that. Supabase is still supported (see
``docs/supabase.md``), but it needs a project, credentials and an authenticated session,
which is too much for "download and double-click". This module provides a local store with
the same shape so the app is fully usable offline, and the Supabase adapter can be
swapped in later without touching the calculators.

Design notes
------------
* One SQLite file, created on first use, inside the writable data directory.
* The column names mirror the API's ``ApplianceIn`` field names exactly, so there is no
  translation layer and no ``watt``/``power``/``power_watts`` confusion.
* ``minutes_per_day`` from Member B's schema is stored as well and exposed as
  ``hours_per_day`` for the calculators, because the original UI collects minutes.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# The API's appliance contract. Keeping this tuple next to the DDL makes drift obvious.
APPLIANCE_FIELDS = (
    "name",
    "category",
    "power_watts",
    "hours_per_day",
    "days_per_month",
    "quantity",
    "voltage",
    "power_factor",
)

# Applied when the caller omits a field. These mirror ``ApplianceIn``'s defaults so a
# record that is valid for the API is also valid for the database.
FIELD_DEFAULTS: dict[str, Any] = {
    "category": None,
    "voltage": None,
    "power_factor": None,
    "days_per_month": 30,
    "quantity": 1,
}

_INTEGER_FIELDS = frozenset({"days_per_month", "quantity"})
_FLOAT_FIELDS = frozenset({"power_watts", "hours_per_day", "voltage", "power_factor"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS appliances (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    category      TEXT,
    power_watts   REAL    NOT NULL,
    hours_per_day REAL    NOT NULL,
    days_per_month INTEGER NOT NULL DEFAULT 30,
    quantity      INTEGER NOT NULL DEFAULT 1,
    voltage       REAL,
    power_factor  REAL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


class StoreError(RuntimeError):
    """Raised when the local store cannot be read or written."""


def default_path() -> Path:
    """Where the database lives.

    ``VOLTSPACE_DB`` overrides it (used by the tests and by anyone who wants the data
    next to the project instead of in the user profile).
    """

    override = os.environ.get("VOLTSPACE_DB")
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get("VOLTSPACE_DATA_DIR")
    root = Path(base).expanduser().resolve() if base else Path.home() / ".voltspace"
    return (root / "voltspace.db").resolve()


def _coerce_field(field: str, value: Any) -> Any:
    """Cast one field to the type its column expects."""

    if value is None:
        return None
    if field in _INTEGER_FIELDS:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise StoreError(f"{field} must be a whole number, got {value!r}") from exc
    if field in _FLOAT_FIELDS:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise StoreError(f"{field} must be a number, got {value!r}") from exc
    return value


def normalise_appliance(appliance: dict[str, Any]) -> dict[str, Any]:
    """Coerce one API-shaped appliance into the values a database row needs.

    Missing optional fields fall back to the same defaults as ``ApplianceIn`` rather than
    being written as NULL, and numeric fields are cast so a JSON ``true`` cannot be stored
    as ``1`` for a wattage.
    """

    row: dict[str, Any] = {}
    for field in APPLIANCE_FIELDS:
        value = appliance.get(field)
        if value is None:
            value = FIELD_DEFAULTS.get(field)
        row[field] = _coerce_field(field, value)

    if not row.get("name"):
        raise StoreError("name is required")
    if row.get("power_watts") is None:
        raise StoreError("power_watts is required")
    if row.get("hours_per_day") is None:
        raise StoreError("hours_per_day is required")
    return row


class ApplianceStore:
    """Thread-safe SQLite wrapper.

    A new connection is opened per operation because SQLite connections are not safe to
    share across threads, and uvicorn serves requests from a threadpool.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path).resolve() if path else default_path()
        self._lock = threading.Lock()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - depends on the host
            raise StoreError(f"cannot create the data directory {self.path.parent}: {exc}") from exc

        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(_SCHEMA)
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise StoreError(f"database error: {exc}") from exc
        finally:
            connection.close()

    # --- reads -------------------------------------------------------------
    def list_appliances(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM appliances ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM appliances").fetchone()
        return int(row["n"])

    # --- writes ------------------------------------------------------------
    def add_appliance(self, appliance: dict[str, Any]) -> dict[str, Any]:
        row = normalise_appliance(appliance)
        columns = ", ".join(APPLIANCE_FIELDS)
        placeholders = ", ".join("?" for _ in APPLIANCE_FIELDS)
        values = [row[field] for field in APPLIANCE_FIELDS]
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO appliances ({columns}) VALUES ({placeholders})", values
            )
            new_id = cursor.lastrowid
            stored = connection.execute(
                "SELECT * FROM appliances WHERE id = ?", (new_id,)
            ).fetchone()
        return dict(stored)

    def replace_appliances(self, appliances: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Overwrite the whole list (used by "save my household" from the frontend)."""

        rows = [normalise_appliance(appliance) for appliance in appliances]
        columns = ", ".join(APPLIANCE_FIELDS)
        placeholders = ", ".join("?" for _ in APPLIANCE_FIELDS)
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM appliances")
            for row in rows:
                connection.execute(
                    f"INSERT INTO appliances ({columns}) VALUES ({placeholders})",
                    [row[field] for field in APPLIANCE_FIELDS],
                )
            stored = connection.execute("SELECT * FROM appliances ORDER BY id").fetchall()
        return [dict(row) for row in stored]

    def update_appliance(self, appliance_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        """Update only the provided fields; unknown/absent fields are left alone."""

        fields = [field for field in APPLIANCE_FIELDS if field in changes]
        if not fields:
            return self.get_appliance(appliance_id)

        values = [_coerce_field(field, changes[field]) for field in fields]
        assignments = ", ".join(f"{field} = ?" for field in fields)
        values.append(appliance_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE appliances SET {assignments}, updated_at = datetime('now') "
                "WHERE id = ?",
                values,
            )
            row = connection.execute(
                "SELECT * FROM appliances WHERE id = ?", (appliance_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_appliance(self, appliance_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM appliances WHERE id = ?", (appliance_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_appliance(self, appliance_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM appliances WHERE id = ?", (appliance_id,))
        return cursor.rowcount > 0

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM appliances")


def to_api_appliance(row: dict[str, Any]) -> dict[str, Any]:
    """Map a stored row onto the calculation API's ``ApplianceIn`` shape."""

    return {
        "appliance_id": str(row["id"]),
        "name": row["name"],
        "category": row.get("category"),
        "power_watts": row["power_watts"],
        "hours_per_day": row["hours_per_day"],
        "days_per_month": row["days_per_month"],
        "quantity": row["quantity"],
        "voltage": row.get("voltage"),
        "power_factor": row.get("power_factor"),
    }
