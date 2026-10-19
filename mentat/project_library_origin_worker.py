"""Fixed credential-free signed-library comparison worker; never loads a library."""
import json
import math
from pathlib import Path
import re
import sys
import time

from mentat.project_library_origin import MAX_RESULT_BYTES, _verify_core
from mentat.project_system_origin import _drain_children
from mentat.project_system_origin_worker import _pairs


def main():
    if sys.platform != "linux":
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
        if not line.endswith(b"\n") or len(line) > 4096:
            raise ValueError()
        outer = json.loads(line, object_pairs_hook=_pairs)
        if (type(outer) is not dict or set(outer) != {"id", "kind", "url"}
                or outer["kind"] != "helper_library_origin" or type(outer["id"]) is not str
                or re.fullmatch("[0-9a-f]{32}", outer["id"]) is None):
            raise ValueError()
        identifier = outer["id"]
        reference = json.loads(outer["url"], object_pairs_hook=_pairs)
        if (type(reference) is not dict or set(reference) != {"root", "deadline"}
                or type(reference["root"]) is not str or len(reference["root"].encode()) > 1024
                or not Path(reference["root"]).is_absolute()
                or type(reference["deadline"]) not in (int, float)
                or not math.isfinite(reference["deadline"])
                or not time.monotonic() < reference["deadline"] <= time.monotonic() + 30):
            raise ValueError()
        value = _verify_core(Path(reference["root"]), reference["deadline"])
        message = {"id": identifier, "type": "result", "result": value}
    except Exception:
        message = {"id": identifier, "type": "error", "code": "library_origin.unverified"}
    _drain_children()
    raw = json.dumps(message, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > MAX_RESULT_BYTES:
        return 1
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()
    # The exact owned group leader remains alive until parent teardown proves
    # that it, command descendants and readers have all become quiescent.
    sys.stdin.buffer.read(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
