"""Linux subprocess guardian: parent pipe loss kills the owned setup process."""

import argparse
import os
import select
import signal
import stat
import subprocess
import sys
import time


def stop_guard(process) -> bool:
    if process is None:
        return True
    try:
        # The guardian and listener share this owned process group. A dead
        # guardian is not evidence that the listener has exited.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            try:
                process.wait(25)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(3)
        deadline = time.monotonic() + 3
        while True:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return process.poll() is not None
            if time.monotonic() >= deadline:
                os.killpg(process.pid, signal.SIGKILL)
                return False  # A later stop must verify group disappearance.
            time.sleep(0.02)
    except OSError:
        return False
    finally:
        if process.stdin is not None:
            process.stdin.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--kind', choices=('node', 'caddy'), required=True)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--resource', required=True)
    args = parser.parse_args()
    if sys.platform != 'linux' or os.getppid() != args.parent_pid or not stat.S_ISFIFO(os.fstat(0).st_mode):
        return 2
    stopping = False
    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, stop)
    # The pipe has no protocol/data: only the parent owns its write end.
    if select.select([0], [], [], 0)[0]:
        return 2
    command = [args.binary, args.resource] if args.kind == 'node' else [args.binary, 'run', '--config', args.resource, '--adapter', 'caddyfile']
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True)
    parent_lost = False
    try:
        while child.poll() is None and not stopping:
            if select.select([0], [], [], 0.1)[0]:
                parent_lost = True
                break
        if child.poll() is None:
            os.kill(child.pid, signal.SIGKILL if parent_lost else signal.SIGTERM)
            try:
                child.wait(20)
            except subprocess.TimeoutExpired:
                os.kill(child.pid, signal.SIGKILL)
                child.wait(3)
        return 2 if parent_lost else child.returncode
    finally:
        if child.poll() is None:
            os.kill(child.pid, signal.SIGKILL)
            child.wait(3)


if __name__ == '__main__':
    raise SystemExit(main())
