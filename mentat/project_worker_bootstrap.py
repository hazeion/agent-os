"""Fixed scope bootstrap; namespace handoff follows verified kernel ownership."""

from __future__ import annotations

import os
import select
import socket
import subprocess
import sys
import time
from pathlib import Path

# The bootstrap is invoked as one fixed isolated script, not a module search
# chosen by browser/worker input. Import only its installed package sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mentat.project_worker_namespace import receive_handoff, namespace_command


def main() -> int:
    control = socket.socket(fileno=int(sys.argv[1]))
    deadline = float(sys.argv[2])
    child = None
    descriptors = ()
    namespace_started = False
    try:
        control.sendall(b"READY\n")
        while time.monotonic() < deadline:
            if child is not None and namespace_started and child.poll() is not None:
                control.sendall(("EXIT " + str(child.returncode) + "\n").encode("ascii"))
                return child.returncode
            ready, _, _ = select.select([control], [], [], min(.05, max(0, deadline - time.monotonic())))
            if not ready:
                continue
            command, received = receive_handoff(control)
            if not command or time.monotonic() >= deadline:
                if received:
                    for descriptor in received:
                        os.close(descriptor)
                break
            if received is not None and child is None:
                descriptors = received
                command = namespace_command(command, descriptors, deadline)
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, pass_fds=descriptors, close_fds=True)
                for descriptor in descriptors:
                    os.close(descriptor)
                descriptors = ()
                namespace_started = True
            elif command == b"DETACH\n" and child is None:
                child = subprocess.Popen(
                    [sys.executable, "-I", "-c",
                     "import os,time; os.setsid(); print('READY',flush=True); time.sleep(60)"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                )
                if child.stdout.readline().strip() != b"READY":
                    return 1
                control.sendall(b"DETACHED\n")
            else:
                if received:
                    for descriptor in received:
                        os.close(descriptor)
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
        for descriptor in descriptors:
            os.close(descriptor)
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
