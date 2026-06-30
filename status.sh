#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec python mentat_lifecycle.py status "$@"
