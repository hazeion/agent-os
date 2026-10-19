"""Fixed credential-free helper-origin worker; no package execution."""
import json
import math
from pathlib import Path
import re
import sys
import time

from mentat.project_system_origin import _drain_children, _verify_core


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def main():
    if sys.platform != 'linux':
        return 1
    import resource
    for name, maximum in ((resource.RLIMIT_AS, 512 * 1024 * 1024), (resource.RLIMIT_CPU, 15),
                          (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_CORE, 0)):
        _, hard = resource.getrlimit(name)
        bound = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
        resource.setrlimit(name, (bound, bound))
    line = sys.stdin.buffer.readline(4097)
    identifier = None
    try:
        if not line.endswith(b'\n') or len(line) > 4096:
            raise ValueError()
        outer = json.loads(line, object_pairs_hook=_pairs)
        if (not isinstance(outer, dict) or set(outer) != {'id', 'kind', 'url'} or outer['kind'] != 'helper_origin'
                or not isinstance(outer['id'], str) or re.fullmatch('[0-9a-f]{32}', outer['id']) is None):
            raise ValueError()
        identifier = outer['id']
        reference = json.loads(outer['url'], object_pairs_hook=_pairs)
        if (not isinstance(reference, dict) or set(reference) != {'root', 'deadline'}
                or not isinstance(reference['root'], str) or len(reference['root'].encode()) > 1024
                or not Path(reference['root']).is_absolute() or type(reference['deadline']) not in (int, float)
                or not math.isfinite(reference['deadline'])
                or not time.monotonic() < reference['deadline'] <= time.monotonic() + 30):
            raise ValueError()
        value = _verify_core(Path(reference['root']), reference['deadline'])
        message = {'id': identifier, 'type': 'result', 'result': value}
    except Exception:
        message = {'id': identifier, 'type': 'error', 'code': 'link_preview.unavailable'}
    # Even failures cannot emit an ordinary outcome while an exact command
    # child remains unreaped. The parent retains/kills/verifies the whole group.
    _drain_children()
    raw = json.dumps(message, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 4096:
        return 1
    sys.stdout.buffer.write(raw + b'\n')
    sys.stdout.buffer.flush()
    # Keep the group leader alive until the owning parent verifies cleanup.
    sys.stdin.buffer.read(1)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
