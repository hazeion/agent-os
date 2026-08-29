from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from link_preview_workers import (
    LinkPreviewWorkerError,
    LinkPreviewWorkerPool,
    minimal_worker_environment,
)


FAKE_WORKER = r'''
import json, os, sys, time
for name in tuple(os.environ):
    if name not in {"LANG", "PYTHONUTF8", "SYSTEMROOT", "WINDIR"}:
        os.environ.pop(name, None)
for line in sys.stdin:
    request = json.loads(line)
    mode = request["url"].split("/", 3)[-1]
    if mode == "invalid":
        print("not-json", flush=True)
        continue
    if mode == "dns-hang":
        print(json.dumps({"type":"phase","phase":"dns"}), flush=True)
        time.sleep(2)
        continue
    if mode == "total-hang":
        print(json.dumps({"type":"phase","phase":"connect"}), flush=True)
        time.sleep(2)
        continue
    if mode == "slow":
        time.sleep(0.5)
    result = {
        "pid": os.getpid(),
        "environment": sorted(os.environ),
        "status": "ready",
    }
    print(json.dumps({"type":"result","id":request["id"],"result":result}), flush=True)
'''


def command():
    return (sys.executable, "-u", "-c", FAKE_WORKER)


class LinkPreviewWorkerTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX process-group regression")
    def test_watchdog_terminates_worker_descendants(self):
        with tempfile.TemporaryDirectory() as temporary:
            pid_path = Path(temporary) / "child.pid"
            script = f'''import json,subprocess,sys,time\nfor line in sys.stdin:\n request=json.loads(line)\n child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n open({str(pid_path)!r},"w").write(str(child.pid))\n print(json.dumps({{"type":"phase","phase":"dns"}}),flush=True)\n time.sleep(30)\n'''
            # macOS framework Python can take several hundred milliseconds to
            # start the grandchild. Keep the total watchdog loose enough to
            # observe the DNS phase, then use the DNS watchdog for the kill.
            with mock.patch("link_preview_workers.DNS_WATCHDOG_SECONDS", 0.15), mock.patch("link_preview_workers.OPERATION_WATCHDOG_SECONDS", 2.0):
                pool = LinkPreviewWorkerPool(command=(sys.executable, "-u", "-c", script), environ={})
                try:
                    with self.assertRaises(LinkPreviewWorkerError):
                        pool.execute(kind="page", normalized_url="https://python.org/child")
                    deadline = time.monotonic() + 2
                    while not pid_path.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    child_pid = int(pid_path.read_text())
                    while time.monotonic() < deadline:
                        try:
                            os.kill(child_pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.02)
                    else:
                        self.fail("worker descendant survived watchdog")
                finally:
                    pool.close()

    def test_environment_allowlist_excludes_credentials_paths_and_proxies(self):
        source = {
            "HOME": "/private/home",
            "NETRC": "/private/netrc",
            "HTTPS_PROXY": "https://proxy",
            "REQUESTS_CA_BUNDLE": "/private/ca",
            "MENTAT_BRIDGE_TOKEN": "secret",
            "SYSTEMROOT": "C:\\Windows",
        }
        source["OPENAI_" + "API_KEY"] = source["HOME"]
        result = minimal_worker_environment(source)
        self.assertEqual(set(result), {"SYSTEMROOT", "LANG", "PYTHONUTF8"})
        pool = LinkPreviewWorkerPool(command=command(), environ=source)
        try:
            worker = pool.execute(kind="page", normalized_url="https://python.org/normal")
            self.assertEqual(set(worker["environment"]), {"LANG", "PYTHONUTF8", "SYSTEMROOT"})
        finally:
            pool.close()

    def test_worker_is_persistent_for_success_and_replaced_after_protocol_failure(self):
        pool = LinkPreviewWorkerPool(command=command(), environ={})
        try:
            first = pool.execute(kind="page", normalized_url="https://python.org/normal")
            second = pool.execute(kind="page", normalized_url="https://python.org/normal")
            third = pool.execute(kind="page", normalized_url="https://python.org/normal")
            self.assertNotEqual(first["pid"], second["pid"])
            self.assertEqual(first["pid"], third["pid"])
            with self.assertRaises(LinkPreviewWorkerError):
                pool.execute(kind="page", normalized_url="https://python.org/invalid")
            unaffected = pool.execute(kind="page", normalized_url="https://python.org/normal")
            replacement = pool.execute(kind="page", normalized_url="https://python.org/normal")
            self.assertEqual(unaffected["pid"], first["pid"])
            self.assertNotIn(replacement["pid"], {first["pid"], second["pid"]})
        finally:
            pool.close()

    def test_dns_and_total_watchdogs_replace_stuck_workers(self):
        with mock.patch("link_preview_workers.DNS_WATCHDOG_SECONDS", 0.15), mock.patch("link_preview_workers.OPERATION_WATCHDOG_SECONDS", 0.35):
            pool = LinkPreviewWorkerPool(command=command(), environ={})
            try:
                for mode in ("dns-hang", "total-hang"):
                    started = time.monotonic()
                    with self.assertRaises(LinkPreviewWorkerError):
                        pool.execute(kind="page", normalized_url=f"https://python.org/{mode}")
                    self.assertLess(time.monotonic() - started, 1.0)
                    self.assertEqual(pool.execute(kind="page", normalized_url="https://python.org/normal")["status"], "ready")
            finally:
                pool.close()

    def test_two_slots_bound_concurrency_and_capacity(self):
        pool = LinkPreviewWorkerPool(command=command(), environ={})
        results: list[dict[str, object]] = []

        def run_slow():
            results.append(pool.execute(kind="page", normalized_url="https://python.org/slow"))

        threads = [threading.Thread(target=run_slow) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
            time.sleep(0.05)
            with self.assertRaises(LinkPreviewWorkerError) as raised:
                pool.execute(kind="page", normalized_url="https://python.org/normal")
            self.assertEqual(raised.exception.code, "link_preview.capacity_unavailable")
            for thread in threads:
                thread.join(timeout=2)
            self.assertEqual(len(results), 2)
            self.assertEqual(len({result["pid"] for result in results}), 2)
        finally:
            pool.close()

    def test_real_worker_rejects_private_target_without_network(self):
        pool = LinkPreviewWorkerPool(environ={"HOME": "/private/home", "HTTPS_PROXY": "https://proxy"})
        try:
            with self.assertRaises(LinkPreviewWorkerError) as raised:
                pool.execute(kind="page", normalized_url="https://127.0.0.1/private")
            self.assertEqual(raised.exception.code, "link_preview.blocked")
        finally:
            pool.close()

    def test_close_is_idempotent_and_rejects_late_work(self):
        pool = LinkPreviewWorkerPool(command=command(), environ={})
        pool.close()
        pool.close()
        with self.assertRaises(LinkPreviewWorkerError):
            pool.execute(kind="page", normalized_url="https://python.org/normal")


if __name__ == "__main__":
    unittest.main()
