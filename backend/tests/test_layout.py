"""The repository layout: global entry points at the root, everything else in backend/.

Keeping this honest matters because the launchers are what a grader double-clicks. If one
of them quietly points at a path that no longer exists, the project looks broken even
though every test passes.
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


class TestRootEntryPoints:
    def test_launchers_live_at_the_root(self):
        for name in ("run_app.bat", "run_app.sh"):
            assert (REPO / name).is_file(), f"{name} should be at the repo root"

    def test_launchers_are_not_in_the_backend_folder(self):
        """A single obvious entry point: the root. Duplicates confuse people."""

        for name in ("run_app.bat", "run_app.sh"):
            assert not (BACKEND / name).exists(), f"backend/{name} is a leftover duplicate"

    def test_batch_launcher_delegates_to_backend(self):
        text = (REPO / "run_app.bat").read_text(encoding="utf-8", errors="replace")
        assert "backend\\start.py" in text
        assert "%HERE%\\start.py" not in text, "still assumes start.py sits beside it"

    def test_shell_launcher_delegates_to_backend(self):
        text = (REPO / "run_app.sh").read_text(encoding="utf-8")
        assert "$BACKEND/start.py" in text
        assert "$HERE/start.py" not in text

    def test_launchers_still_find_a_python(self):
        """The fallback chain is the whole point of these files."""

        batch = (REPO / "run_app.bat").read_text(encoding="utf-8", errors="replace")
        for token in ("\\.venv\\Scripts\\python.exe", "where py", "where python", "C:\\Python"):
            assert token in batch, f"run_app.bat should try {token!r}"

        shell = (REPO / "run_app.sh").read_text(encoding="utf-8")
        assert "command -v python3" in shell

    def test_launchers_pass_options_through(self):
        batch = (REPO / "run_app.bat").read_text(encoding="utf-8", errors="replace")
        shell = (REPO / "run_app.sh").read_text(encoding="utf-8")
        assert '"%BACKEND%\\start.py" %*' in batch
        assert '"$@"' in shell


class TestBackendOwnsTheCode:
    def test_backend_holds_the_application_packages(self):
        for name in ("app", "web", "desktop", "tests", "tools", "docs", "db"):
            assert (BACKEND / name).is_dir(), f"backend/{name} missing"

    def test_start_py_stays_with_the_backend(self):
        """It resolves .data/, tools/ and app/ relative to its own folder."""

        assert (BACKEND / "start.py").is_file()
        assert not (REPO / "start.py").exists()

    def test_deployment_configs_sit_at_the_root(self):
        for name in ("Dockerfile", "render.yaml", ".dockerignore", ".env.example"):
            assert (REPO / name).is_file(), f"{name} should be at the repo root"

    def test_dockerfile_still_copies_the_backend_folder(self):
        """Root-level config must keep working after the move."""

        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        assert "COPY backend/requirements.txt" in text
        assert "COPY backend/ ./" in text

    def test_render_blueprint_still_points_at_backend(self):
        text = (REPO / "render.yaml").read_text(encoding="utf-8")
        assert text.count("rootDir: backend") == 2
        # The launchers moved, but the start command never used them.
        assert "startCommand: python start.py --no-browser" in text
