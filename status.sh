#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="python3"
if [ -x "$PWD/.venv/Scripts/python.exe" ]; then
  PYTHON="$PWD/.venv/Scripts/python.exe"
elif [ -x "$PWD/.venv/bin/python" ]; then
  PYTHON="$PWD/.venv/bin/python"
fi

exec "$PYTHON" mentat_lifecycle.py status "$@"
