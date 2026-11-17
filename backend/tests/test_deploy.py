"""Deployment support: binding address, .env loading, and the config files.

These matter because a hosting platform fails in a confusing way when they are wrong:
binding 127.0.0.1 on a cloud host makes the health check time out while the log looks
perfectly healthy.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


def _start_module():
    """Import backend/start.py without running it."""

    spec = importlib.util.spec_from_file_location("voltspace_start", BACKEND / "start.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def start_module():
    return _start_module()


@pytest.fixture()
def clean_env(monkeypatch):
    """No leftover PORT/HOST from the machine or the test runner."""

    for name in ("PORT", "HOST"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


class TestResolveBind:
    def test_local_default_is_loopback(self, start_module, clean_env):
        host, port, public = start_module.resolve_bind()
        assert host == "127.0.0.1"
        assert port == start_module.DEFAULT_PORT
        assert public is False

    def test_platform_port_binds_all_interfaces(self, start_module, clean_env):
        """A host that sets $PORT expects 0.0.0.0, not 127.0.0.1."""

        clean_env.setenv("PORT", "10000")
        host, port, public = start_module.resolve_bind()
        assert host == "0.0.0.0"
        assert port == 10000
        assert public is True

    def test_explicit_host_wins_over_platform_port(self, start_module, clean_env):
        clean_env.setenv("PORT", "10000")
        host, port, _ = start_module.resolve_bind("127.0.0.1")
        assert host == "127.0.0.1"
        assert port == 10000

    def test_explicit_port_wins_over_environment(self, start_module, clean_env):
        clean_env.setenv("PORT", "10000")
        _, port, _ = start_module.resolve_bind(None, 9000)
        assert port == 9000

    def test_host_environment_variable_is_honoured(self, start_module, clean_env):
        clean_env.setenv("HOST", "0.0.0.0")
        host, _, public = start_module.resolve_bind()
        assert host == "0.0.0.0"
        assert public is True

    def test_garbage_port_is_ignored(self, start_module, clean_env):
        clean_env.setenv("PORT", "not-a-number")
        host, port, _ = start_module.resolve_bind()
        assert host == "127.0.0.1"
        assert port == start_module.DEFAULT_PORT

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("0.0.0.0", "http://127.0.0.1:8000/"),
            ("127.0.0.1", "http://127.0.0.1:8000/"),
            ("localhost", "http://localhost:8000/"),
        ],
    )
    def test_display_url_is_clickable(self, start_module, host, expected):
        """0.0.0.0 is not a browser address; print something that works."""

        assert start_module.display_url(host, 8000) == expected


class TestDotenv:
    def test_missing_file_is_harmless(self, start_module, tmp_path):
        assert start_module.load_dotenv(tmp_path / "nope.env") == []

    def test_values_are_loaded(self, start_module, tmp_path, monkeypatch):
        monkeypatch.delenv("VOLTSPACE_EXAMPLE_KEY", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# comment\n\nVOLTSPACE_EXAMPLE_KEY=abc123\nQUOTED=\"x=1\"\n", encoding="utf-8"
        )
        applied = start_module.load_dotenv(env_file)

        assert "VOLTSPACE_EXAMPLE_KEY" in applied
        assert os.environ["VOLTSPACE_EXAMPLE_KEY"] == "abc123"
        monkeypatch.delenv("VOLTSPACE_EXAMPLE_KEY", raising=False)
        monkeypatch.delenv("QUOTED", raising=False)

    def test_real_environment_wins(self, start_module, tmp_path, monkeypatch):
        """A platform's variable must never be overwritten by a copied .env file."""

        monkeypatch.setenv("VOLTSPACE_STORAGE", "supabase")
        env_file = tmp_path / ".env"
        env_file.write_text("VOLTSPACE_STORAGE=local\n", encoding="utf-8")

        start_module.load_dotenv(env_file)

        assert os.environ["VOLTSPACE_STORAGE"] == "supabase"

    def test_env_example_lists_every_supported_variable(self):
        """The template has to mention what the code actually reads."""

        example = (REPO / ".env.example").read_text(encoding="utf-8")
        for name in (
            "VOLTSPACE_STORAGE",
            "VOLTSPACE_SUPABASE_URL",
            "VOLTSPACE_SUPABASE_SERVICE_KEY",
            "VOLTSPACE_HOUSEHOLD_ID",
        ):
            assert name in example, f"{name} missing from .env.example"


class TestDeploymentFiles:
    def test_render_blueprint_points_at_the_app(self):
        text = (REPO / "render.yaml").read_text(encoding="utf-8")
        assert "rootDir: backend" in text
        assert "start.py --no-browser" in text
        assert "healthCheckPath: /health" in text
        # Secrets must not be committed; sync:false means "fill in on the dashboard".
        assert text.count("sync: false") >= 3

    def test_dockerfile_matches_what_the_app_needs(self):
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        assert "backend/requirements.txt" in text
        assert "start.py" in text
        assert "7860" in text, "Hugging Face Spaces expects port 7860"
        assert "/health" in text, "the container should health-check /health"

    def test_dockerignore_excludes_secrets_and_virtualenvs(self):
        text = (REPO / ".dockerignore").read_text(encoding="utf-8")
        for pattern in (".env", "backend/.venv", "backend/.data"):
            assert pattern in text, f"{pattern} should not be copied into the image"

    def test_deploy_doc_exists_and_covers_the_options(self):
        text = (REPO / "docs" / "deploy.md").read_text(encoding="utf-8")
        for topic in ("Cloudflare Tunnel", "Render", "Docker", "/health", "SQLite"):
            assert topic in text, f"docs/deploy.md should mention {topic}"

    def test_no_secret_looking_values_in_tracked_config(self):
        """The config files must never carry a real key."""

        for name in ("render.yaml", ".env.example", "Dockerfile"):
            text = (REPO / name).read_text(encoding="utf-8")
            assert "sb_secret_" not in text, f"{name} contains a secret key"
            assert "eyJhbGciOi" not in text, f"{name} contains a JWT"
