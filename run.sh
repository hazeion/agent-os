#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python agent_os_lifecycle.py preflight "$@"
export AGENT_OS_LAUNCHER_PID=$$
python server.py "$@" &
child_pid=$!
cleanup() {
  if kill -0 "$child_pid" 2>/dev/null; then
    kill "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM
wait "$child_pid"
