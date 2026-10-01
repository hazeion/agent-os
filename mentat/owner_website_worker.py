"""Fixed guarded entry point for the authenticated website's existing supervisor."""

import os
from pathlib import Path
import sys

# Source-checkout and installed execution select this file's own application,
# never a browser or working-directory-selected module path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mentat.web_runtime import run_gateway


if __name__ == '__main__':
    try:
        result = run_gateway(host='127.0.0.1', port=8888,
            data_dir=Path(os.environ['MENTAT_DATA_DIR']),
            runtime_environment={'MENTAT_LAUNCHER_PID': str(os.getpid())},
            owner_origin=os.environ['MENTAT_OWNER_ORIGIN'])
    except Exception:
        result = 2
    raise SystemExit(result)
