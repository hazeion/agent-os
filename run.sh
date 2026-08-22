#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
cd "$SCRIPT_DIR"

PYTHON="python3"
if [ -x "$PWD/.venv/Scripts/python.exe" ]; then
  PYTHON="$PWD/.venv/Scripts/python.exe"
elif [ -x "$PWD/.venv/bin/python" ]; then
  PYTHON="$PWD/.venv/bin/python"
fi

exec "$PYTHON" -m mentat.cli start "$@"
