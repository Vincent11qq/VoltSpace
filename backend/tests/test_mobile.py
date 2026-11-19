"""Tests for the phone path: the Flet UI served as a web page."""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def _start_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("voltspace_start_mobile", BACKEND / "start.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestFletWebMode:
    def test_desktop_app_serves_web_mode_from_the_environment(self):
        """The window and the web page are the same code; only the view differs."""

        source = (BACKEND / "desktop" / "app.py").read_text(encoding="utf-8")
        assert "VOLTSPACE_FLET_WEB" in source
        assert "AppView.WEB_BROWSER" in source
        # It must bind all interfaces, otherwise a phone cannot reach it.
        assert 'os.environ.get("VOLTSPACE_FLET_HOST", "0.0.0.0")' in source

    def test_launcher_passes_the_web_environment_to_the_child(self):
        source = (BACKEND / "start.py").read_text(encoding="utf-8")
        body = source[source.index("def run_flet_web") : source.index("def setup_environment")]
        assert '"VOLTSPACE_FLET_WEB": "1"' in body
        assert '"VOLTSPACE_FLET_HOST"' in body
        assert '"VOLTSPACE_FLET_PORT"' in body

    def test_web_mode_has_its_own_cli_flag(self):
        source = (BACKEND / "start.py").read_text(encoding="utf-8")
        assert '"--flet-web"' in source
        assert "args.flet_web" in source

    def test_web_mode_explains_how_to_install_flet_web(self):
        """flet-web is optional; the message must say how to add it."""

        source = (BACKEND / "start.py").read_text(encoding="utf-8")
        body = source[source.index("def run_flet_web") : source.index("def setup_environment")]
        assert "flet-web" in body
        assert "flet_web" in body  # the import probe

    def test_lan_address_is_usable(self):
        start = _start_module()
        address = start.lan_address()
        assert address and address.count(".") == 3, address
        # It may legitimately be loopback on a machine without a network.
        assert isinstance(address, str)

    def test_requirements_desktop_mentions_web_mode(self):
        text = (BACKEND / "requirements-desktop.txt").read_text(encoding="utf-8")
        assert "flet-web" in text
