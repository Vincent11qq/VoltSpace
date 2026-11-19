"""Choose the household store: Supabase when configured, otherwise local SQLite.

Configuration is entirely by environment variable, so nothing about a specific project
is baked into the source:

======================  ==========================================================
``VOLTSPACE_STORAGE``   ``auto`` (default) / ``supabase`` / ``local``
``VOLTSPACE_SUPABASE_URL``      ``https://<project>.supabase.co``
``VOLTSPACE_SUPABASE_KEY``      the API key to use
``VOLTSPACE_SUPABASE_SERVICE_KEY``  optional; used instead of the above when set
``VOLTSPACE_SUPABASE_TABLE``    defaults to ``appliances``
``VOLTSPACE_HOUSEHOLD_ID``      optional uuid, to scope rows to one household
======================  ==========================================================

Behaviour
---------
``auto`` (the default) tries Supabase and falls back to SQLite if Supabase is
misconfigured or unreachable, printing why. That keeps ``run_app.bat`` working on a
machine with no cloud setup, which is the common case for a demo.

``supabase`` fails hard instead, so a misconfiguration cannot silently look like it
works while writing locally.
"""

from __future__ import annotations

import os
from typing import Any

from .store import ApplianceStore, StoreError

SUPABASE_URL = "VOLTSPACE_SUPABASE_URL"
SUPABASE_KEY = "VOLTSPACE_SUPABASE_KEY"
SUPABASE_SERVICE_KEY = "VOLTSPACE_SUPABASE_SERVICE_KEY"
SUPABASE_TABLE = "VOLTSPACE_SUPABASE_TABLE"
HOUSEHOLD_ID = "VOLTSPACE_HOUSEHOLD_ID"
STORAGE_MODE = "VOLTSPACE_STORAGE"


def _mode() -> str:
    mode = (os.environ.get(STORAGE_MODE) or "auto").strip().lower()
    if mode not in {"auto", "supabase", "local"}:
        raise StoreError(
            f"{STORAGE_MODE} must be auto, supabase or local (got {mode!r})"
        )
    return mode


def supabase_settings() -> dict[str, Any] | None:
    """The Supabase settings, or ``None`` when it is not configured at all."""

    url = (os.environ.get(SUPABASE_URL) or "").strip()
    key = (
        os.environ.get(SUPABASE_SERVICE_KEY)
        or os.environ.get(SUPABASE_KEY)
        or ""
    ).strip()
    if not url and not key:
        return None
    if not url or not key:
        missing = SUPABASE_URL if not url else f"{SUPABASE_KEY} (or {SUPABASE_SERVICE_KEY})"
        raise StoreError(f"Supabase is partly configured: {missing} is not set")
    return {
        "url": url,
        "key": key,
        "table": (os.environ.get(SUPABASE_TABLE) or "appliances").strip(),
        "household_id": (os.environ.get(HOUSEHOLD_ID) or "").strip() or None,
    }


def create_store() -> Any:
    """Return a store ready to use. Never returns ``None``."""
    from .store_supabase import SupabaseStore

    mode = _mode()

    if mode == "local":
        return ApplianceStore()

    try:
        settings = supabase_settings()
    except StoreError as exc:
        if mode == "supabase":
            raise
        print(f"[voltspace] Supabase is misconfigured, using local SQLite instead: {exc}")
        return ApplianceStore()

    if settings is None:
        if mode == "supabase":
            raise StoreError(
                "VOLTSPACE_STORAGE=supabase but neither "
                f"{SUPABASE_URL} nor {SUPABASE_KEY} is set"
            )
        return ApplianceStore()

    store = SupabaseStore(**settings)
    try:
        # Prove the table is readable with a known layout before serving requests.
        count = store.count()
    except StoreError as exc:
        if mode == "supabase":
            raise
        print(
            "[voltspace] Supabase is configured but not usable, using local SQLite "
            f"instead:\n[voltspace]   {exc}"
        )
        return ApplianceStore()

    print(f"[voltspace] household store: Supabase ({store.url}, {count} saved row(s))")
    return store


def describe(store: Any) -> str:
    """The value reported by ``/health``."""

    return getattr(store, "backend_name", "local-sqlite")
