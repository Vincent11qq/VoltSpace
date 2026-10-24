#!/usr/bin/env bash
# ===========================================================================
# VoltSpace - one-click launcher (macOS / Linux)
#
#   ./run_app.sh              start the app and open the browser
#   ./run_app.sh --port 8080
#   ./run_app.sh --flet       also try the Flet desktop UI
#   ./run_app.sh --check      verify the environment only
# ===========================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PY=""
for candidate in ".venv/bin/python" ".venv314/bin/python"; do
  if [ -x "$candidate" ]; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then PY="$(command -v python3 || command -v python || true)"; fi

if [ -z "$PY" ]; then
  echo "[X] Python 3.10+ was not found."
  echo "    Install it, then run once:"
  echo "        python3 -m venv .venv"
  echo "        .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Using Python: $PY"
exec "$PY" "$HERE/start.py" "$@"
