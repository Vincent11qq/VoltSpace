"""Connectivity check for the VoltSpace Supabase project.

Fixed version of Member B's `supabase.py`. Changes from the original:

1. ``_init_``  -> ``__init__``      (the constructor was never called, so every
                                     attribute was missing)
2. ``_name_`` -> ``__name__``       (and ``_main_`` -> ``__main__``)
3. ``python-dotenv`` is now optional. If it is installed, a ``.env`` file is read;
   otherwise plain environment variables are used. The original hard-required it.
4. The URL is validated before use, and every failure returns an actionable message
   instead of a raw body or a bare exception.

Only needs ``httpx``, which the project already has.

Usage
-----
Set the two variables, then run::

    PowerShell:
        $env:VOLTSPACE_SUPABASE_URL = "https://<project>.supabase.co"
        $env:VOLTSPACE_SUPABASE_KEY = "<service_role key>"
        python supabase.py

    cmd:
        set VOLTSPACE_SUPABASE_URL=https://<project>.supabase.co
        set VOLTSPACE_SUPABASE_KEY=<service_role key>
        python supabase.py

The service_role key is preferred when both are set, because the project's row level
security only grants access to ``authenticated`` users, and the backend has no login.
Keep the service_role key on the server - never ship it to a client.
"""

from __future__ import annotations

import os
import sys

import httpx

# python-dotenv is optional: use it when present, ignore it when not.
try:  # pragma: no cover - depends on the environment
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

URL_ENV = "VOLTSPACE_SUPABASE_URL"
KEY_ENV = "VOLTSPACE_SUPABASE_KEY"
SERVICE_KEY_ENV = "VOLTSPACE_SUPABASE_SERVICE_KEY"


class SupabaseConnection:
    """Holds the project URL and key, and can check that they work."""

    def __init__(self) -> None:
        self.url = (os.environ.get(URL_ENV) or "").strip().rstrip("/")
        self.key = (
            os.environ.get(SERVICE_KEY_ENV) or os.environ.get(KEY_ENV) or ""
        ).strip()

        if not self.url or not self.key:
            missing = []
            if not self.url:
                missing.append(URL_ENV)
            if not self.key:
                missing.append(f"{KEY_ENV} (or {SERVICE_KEY_ENV})")
            raise ValueError(
                "Supabase configuration is missing: " + ", ".join(missing) + ". "
                "Get both values from the Supabase dashboard: "
                "Project Settings -> API."
            )

        if not self.url.startswith("https://"):
            raise ValueError(
                f"{URL_ENV} must start with https:// (got {self.url!r})."
            )
        if ".supabase.co" not in self.url:
            raise ValueError(
                f"{URL_ENV} should look like https://<project>.supabase.co "
                f"(got {self.url!r})."
            )

        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Accept": "application/json",
        }

    def test_connection(self, table: str | None = "appliances") -> dict:
        """Check the REST endpoint, and optionally that a table can be read.

        Returns ``{"connected": bool, "message": str, "detail": ...}`` rather than
        raising, so it is safe to call from a script or a test.
        """

        # 1. Does the project answer at all?
        try:
            response = httpx.get(
                f"{self.url}/rest/v1/",
                headers=self.headers,
                timeout=15.0,
                follow_redirects=True,
            )
        except httpx.HTTPError as error:
            return {
                "connected": False,
                "message": (
                    f"Cannot reach {self.url}: {error}. "
                    "Check the project URL, and that the project is not paused or deleted."
                ),
            }

        if response.status_code >= 400:
            return {
                "connected": False,
                "message": (
                    f"The project answered HTTP {response.status_code}. "
                    "A 401 usually means the API key is wrong or expired."
                ),
                "detail": response.text[:200],
            }

        # 2. Can this key read the table we actually use?
        if table:
            try:
                table_response = httpx.get(
                    f"{self.url}/rest/v1/{table}",
                    headers={**self.headers, "Prefer": "count=exact"},
                    params={"select": "id", "limit": "1"},
                    timeout=15.0,
                    follow_redirects=True,
                )
            except httpx.HTTPError as error:
                return {
                    "connected": False,
                    "message": f"Reached the project but reading '{table}' failed: {error}",
                }

            if table_response.status_code == 404:
                return {
                    "connected": False,
                    "message": (
                        f"Connected, but the '{table}' table does not exist. "
                        "Run appliances.sql in the Supabase SQL editor."
                    ),
                }
            if table_response.status_code >= 400:
                return {
                    "connected": False,
                    "message": (
                        f"Connected, but reading '{table}' failed with HTTP "
                        f"{table_response.status_code}. Run security.sql, or use the "
                        "service_role key."
                    ),
                    "detail": table_response.text[:200],
                }

        return {
            "connected": True,
            "message": f"Supabase connection successful ({self.url}).",
        }


def main() -> int:
    try:
        connection = SupabaseConnection()
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1

    result = connection.test_connection()
    print(result["message"])
    if result.get("detail"):
        print(f"  response: {result['detail']}")
    return 0 if result["connected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
