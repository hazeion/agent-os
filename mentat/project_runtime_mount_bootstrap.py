"""Fixed foreground read-only image helper; no caller executable or options."""
from __future__ import annotations

import ctypes
import os
import signal
from pathlib import Path
import re
import sys


def main():
    if not sys.platform.startswith("linux"):
        return 1
    import resource
    parent = os.getppid()
    if parent <= 1:
        return 1
    library = ctypes.CDLL(None, use_errno=True)
    if library.prctl(1, signal.SIGTERM, 0, 0, 0) or library.prctl(4, 0, 0, 0, 0):
        return 1
    if os.getppid() != parent:
        return 1
    descriptor = int(sys.argv[1])
    name = Path(sys.argv[2]).parent.name
    if re.fullmatch(r"mentat-runtime-image-[0-9a-f]{32}", name) is None:
        return 1
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.set_inheritable(descriptor, True)
    os.execve("/usr/bin/squashfuse", ["/usr/bin/squashfuse", "-f", "-s", "-o", "ro,nosuid,nodev",
                                    "/proc/self/fd/" + str(descriptor), sys.argv[2]],
              {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent"})


if __name__ == "__main__":
    raise SystemExit(main())
