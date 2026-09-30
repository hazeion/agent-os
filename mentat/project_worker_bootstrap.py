"""Fixed inert scope bootstrap. No Agent, input, provider or execution API.

The only implemented commands are owned-process qualification operations.
Production namespace/Run handoff will be a separate reviewed protocol.
"""

from __future__ import annotations

import os
import select
import socket
import subprocess
import sys
import time


def main() -> int:
    control = socket.socket(fileno=int(sys.argv[1]))
    deadline = float(sys.argv[2])
    child = None
    try:
        control.sendall(b"READY\n")
        while time.monotonic() < deadline:
            ready, _, _ = select.select([control], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            command = control.recv(64)
            if not command or time.monotonic() >= deadline:
                break
            if command == b"DETACH\n" and child is None:
                child = subprocess.Popen(
                    [sys.executable, "-I", "-c",
                     "import os,time; os.setsid(); print('READY',flush=True); time.sleep(60)"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                if child.stdout.readline().strip() != b"READY":
                    return 1
                control.sendall(b"DETACHED\n")
            else:
                return 1
        return 0
    finally:
        # EOF/startup refusal cannot leave the fixed qualification child behind.
        if child is not None:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=1)
            if child.stdout is not None:
                child.stdout.close()
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
