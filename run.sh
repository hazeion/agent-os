#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="python"
if [ -x "$PWD/.venv/Scripts/python.exe" ]; then
  PYTHON="$PWD/.venv/Scripts/python.exe"
elif [ -x "$PWD/.venv/bin/python" ]; then
  PYTHON="$PWD/.venv/bin/python"
fi

"$PYTHON" agent_os_lifecycle.py preflight "$@"
export AGENT_OS_LAUNCHER_PID=$$
"$PYTHON" server.py "$@" &
child_pid=$!
cleanup() {
  if kill -0 "$child_pid" 2>/dev/null; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM
wait "$child_pid"
