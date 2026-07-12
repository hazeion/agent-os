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

"$PYTHON" "$SCRIPT_DIR/mentat_lifecycle.py" preflight "$@"
export MENTAT_LAUNCHER_PID=$$
"$PYTHON" "$SCRIPT_DIR/server.py" "$@" &
child_pid=$!
cleanup() {
  if kill -0 "$child_pid" 2>/dev/null; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM
wait "$child_pid"
