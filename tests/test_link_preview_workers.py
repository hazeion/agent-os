from __future__ import annotations

import json
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
        from link_preview_workers import OPERATION_WATCHDOG_SECONDS

        # Preparation receipt only: production execute never accepts this frame.
        # Consume it from each exact generation before applying short operation
        # assertions; interpreter startup is not a DNS or response operation.
        ready_worker = FAKE_WORKER.replace(
            "for line in sys.stdin:",
            'sys.stdout.buffer.write((json.dumps({"type":"fixture_ready","pid":os.getpid()}) '
            '+ "\\n").encode("utf-8")); sys.stdout.buffer.flush()\n'
            "for line in sys.stdin:",
        )
        ready_command = (sys.executable, "-u", "-c", ready_worker)
        setup_watchdog = OPERATION_WATCHDOG_SECONDS

        def await_fixture_ready(slot, deadline):
            process, messages = slot._process, slot._messages
            self.assertIsNotNone(process)
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0)
            raw = messages.get(timeout=remaining)
            expected = json.dumps({"type": "fixture_ready", "pid": process.pid}).encode() + b"\n"
            self.assertEqual(raw, expected)
            self.assertLessEqual(time.monotonic(), deadline)
            self.assertIs(slot._process, process)
            self.assertIs(slot._messages, messages)
            self.assertIsNone(process.poll())
            return process

        with mock.patch("link_preview_workers.DNS_WATCHDOG_SECONDS", 0.15), mock.patch("link_preview_workers.OPERATION_WATCHDOG_SECONDS", 0.35):
            pool = LinkPreviewWorkerPool(command=ready_command, environ={})
            try:
                setup_deadline = time.monotonic() + setup_watchdog
                initial = [await_fixture_ready(slot, setup_deadline) for slot in pool._slots]
                self.assertNotEqual(initial[0].pid, initial[1].pid)
                for index, mode in enumerate(("dns-hang", "total-hang")):
                    target, unaffected = pool._slots[index], pool._slots[1 - index]
                    old, stable = target._process, unaffected._process
                    started = time.monotonic()
                    with self.assertRaises(LinkPreviewWorkerError):
                        pool.execute(kind="page", normalized_url=f"https://python.org/{mode}")
                    self.assertLess(time.monotonic() - started, 1.0)
                    self.assertIsNotNone(old.poll())
                    self.assertIsNot(target._process, old)
                    self.assertNotEqual(target._process.pid, old.pid)
                    self.assertIs(unaffected._process, stable)
                    self.assertIsNone(stable.poll())
                    replacement = await_fixture_ready(target, time.monotonic() + setup_watchdog)
                    self.assertNotIn(replacement.pid, {old.pid, stable.pid})
                    # Round-robin returns unaffected then replacement. Both normal
                    # calls retain the same patched 0.35-second operation budget.
                    for expected_process in (stable, replacement):
                        result = pool.execute(kind="page", normalized_url="https://python.org/normal")
                        self.assertEqual(result["status"], "ready")
                        self.assertEqual(result["pid"], expected_process.pid)
            finally:
                pool.close()

    def test_two_slots_bound_concurrency_and_capacity(self):
        pool = LinkPreviewWorkerPool(command=command(), environ={})
        results: list[dict[str, object]] = []
        entered = threading.Event()
        release = threading.Event()
        entered_lock = threading.Lock()
        entered_count = 0

        def occupy(slot):
            def execute(*, kind: str, url: str):
                nonlocal entered_count
                with entered_lock:
                    entered_count += 1
                    if entered_count == 2:
                        entered.set()
                release.wait(timeout=2)
                return {"pid": id(slot), "status": "ready"}

            return execute

        for slot in pool._slots:
            slot.execute = occupy(slot)

        def run_slow():
            results.append(pool.execute(kind="page", normalized_url="https://python.org/slow"))

        threads = [threading.Thread(target=run_slow) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
            self.assertTrue(entered.wait(timeout=2))
            with self.assertRaises(LinkPreviewWorkerError) as raised:
                pool.execute(kind="page", normalized_url="https://python.org/normal")
            self.assertEqual(raised.exception.code, "link_preview.capacity_unavailable")
        finally:
            release.set()
            for thread in threads:
                thread.join(timeout=2)
            pool.close()
        self.assertEqual(len(results), 2)
        self.assertEqual(len({result["pid"] for result in results}), 2)

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
