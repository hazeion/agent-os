from __future__ import annotations

import contextlib
import json
import os
import queue
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from types import SimpleNamespace

import link_preview_workers as worker_module

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


class WorkerCleanupContractTests(unittest.TestCase):
    class Pipe:
        def __init__(self, *, fail=None, on_write=None):
            self.fail = fail
            self.on_write = on_write
            self.close_calls = 0
            self.closed = False

        def close(self):
            self.close_calls += 1
            if self.close_calls != 1:
                raise AssertionError("an ambiguous stream was closed twice")
            if self.fail == "before":
                raise OSError("synthetic before-close failure")
            self.closed = True
            if self.fail == "after":
                raise OSError("synthetic after-close failure")

        def write(self, raw):
            if self.closed:
                raise ValueError("closed synthetic stream")
            if self.on_write is not None:
                self.on_write(raw)
            return len(raw)

        def flush(self):
            if self.closed:
                raise ValueError("closed synthetic stream")

    class Process:
        pid = 4321
        _mentat_process_group = pid

        def __init__(self, events, *, windows=False, fail=None):
            self.events = events
            self.windows = windows
            self.returncode = None
            self.reaped = False
            self.stdin = WorkerCleanupContractTests.Pipe(fail=fail)
            self.stdout = WorkerCleanupContractTests.Pipe()
            self.health_hook = None

        def poll(self):
            if self.windows:
                return self.returncode
            if self.health_hook is not None:
                return self.health_hook()
            raise AssertionError("POSIX health/cleanup reaped through poll")

        def wait(self, *, timeout):
            if not self.windows:
                if not any(event == ("signal", 9) for event in self.events):
                    raise AssertionError("leader reaped before last group signal")
            self.events.append(("wait", timeout))
            self.returncode = 0
            self.reaped = True
            return 0

        def terminate(self):
            raise AssertionError("POSIX Popen.terminate can poll/reap")

        def kill(self):
            raise AssertionError("POSIX Popen.kill can poll/reap")

    def slot(self, process):
        from link_preview_workers import _WorkerSlot
        slot = object.__new__(_WorkerSlot)
        slot._process = process
        slot._reader = None
        slot._cleanup_state = None
        slot._lifecycle_lock = threading.RLock()
        slot._lock = threading.Lock()
        slot._shutdown = False
        slot._messages = queue.Queue()
        slot._output_failed = threading.Event()
        slot._clock = time.monotonic
        slot._operation_watchdog_seconds = None
        slot._maximum_line_bytes = None
        slot._spawn = mock.Mock(side_effect=AssertionError("unexpected replacement spawn"))
        return slot

    @contextlib.contextmanager
    def posix_effects(self, process, *, waitid=True, group_absent=True):
        events = process.events
        def observe(_kind, pid, _options):
            self.assertEqual(pid, process.pid)
            return SimpleNamespace(si_pid=pid)
        def signal_group(group, kind):
            self.assertEqual(group, process.pid)
            if kind:
                self.assertFalse(process.reaped, "nonzero signal after reap")
                events.append(("signal", kind))
            else:
                self.assertTrue(process.reaped)
                events.append(("observe", 0))
                if group_absent:
                    raise ProcessLookupError()
        with mock.patch.object(worker_module.os, "name", "posix"), \
             mock.patch.multiple(worker_module.os, waitid=observe if waitid else None,
                                 P_PID=1, WEXITED=4, WNOHANG=1, WNOWAIT=16, create=True), \
             mock.patch.multiple(worker_module.signal, SIGTERM=15, SIGKILL=9,
                                 SIGCHLD=17, SIG_DFL=0, SIG_IGN=1, create=True), \
             mock.patch.object(worker_module.signal, "getsignal", return_value=0, create=True), \
             mock.patch.object(worker_module.os, "killpg", side_effect=signal_group, create=True) as control:
            yield control

    def test_final_group_signal_precedes_reap_even_when_leader_already_exited(self):
        events = []
        process = self.Process(events)
        slot = self.slot(process)
        with self.posix_effects(process):
            slot.close()
            slot.close()
        self.assertEqual(events[:2], [("signal", 15), ("signal", 9)])
        self.assertEqual(events[2][0], "wait")
        self.assertEqual(events[3:], [("observe", 0)])
        self.assertIsNone(slot._process)
        self.assertEqual((process.stdin.close_calls, process.stdout.close_calls), (1, 1))

    def test_no_waitid_fallback_keeps_leader_unreaped_through_existing_grace(self):
        events = []
        process = self.Process(events)
        slot = self.slot(process)
        now = [0.0]
        def sleep(delay):
            self.assertGreater(delay, 0)
            now[0] += delay
        with self.posix_effects(process, waitid=False), \
             mock.patch.object(worker_module.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(worker_module.time, "sleep", side_effect=sleep):
            slot.close()
        self.assertAlmostEqual(now[0], 0.5)
        self.assertEqual(events[:2], [("signal", 15), ("signal", 9)])
        self.assertLessEqual(events[2][1], 0.5)
        self.assertIsNone(slot._process)

    def test_nondefault_sigchld_refuses_spawn_and_existing_group_control(self):
        from link_preview_workers import _WorkerSlot
        for disposition in (1, lambda *_args: None):
            with self.subTest(disposition=type(disposition).__name__):
                process = self.Process([])
                slot = self.slot(process)
                with self.posix_effects(process, waitid=False) as control, \
                     mock.patch.object(worker_module.signal, "getsignal", return_value=disposition), \
                     mock.patch.object(worker_module.subprocess, "Popen") as launch:
                    with self.assertRaises(LinkPreviewWorkerError) as caught:
                        slot.close()
                    control.assert_not_called()
                    self.assertIs(caught.exception._mentat_worker_owner, slot)
                    self.assertIs(slot._process, process)
                    self.assertEqual((process.stdin.close_calls, process.stdout.close_calls), (0, 0))
                    fresh = self.slot(None)
                    with self.assertRaises(LinkPreviewWorkerError):
                        _WorkerSlot._spawn(fresh)
                    launch.assert_not_called()

    def test_late_reap_or_absence_cannot_clear_cleanup_ownership(self):
        for phase in ("wait", "probe"):
            with self.subTest(phase=phase):
                process = self.Process([])
                slot = self.slot(process)
                now = [0.0]
                original_wait = process.wait
                def wait(*, timeout):
                    value = original_wait(timeout=timeout)
                    if phase == "wait":
                        now[0] = 0.6
                    return value
                process.wait = wait
                with self.posix_effects(process) as control, \
                     mock.patch.object(worker_module.time, "monotonic", side_effect=lambda: now[0]):
                    original_control = control.side_effect
                    def probe(group, kind):
                        if kind == 0 and phase == "probe":
                            now[0] = 0.6
                        return original_control(group, kind)
                    control.side_effect = probe
                    with self.assertRaises(LinkPreviewWorkerError) as caught:
                        slot.close()
                    calls = control.call_count
                    with self.assertRaises(LinkPreviewWorkerError) as again:
                        slot.close()
                    self.assertEqual(control.call_count, calls)
                self.assertIs(again.exception, caught.exception)
                self.assertIs(slot._process, process)
                self.assertIs(caught.exception._mentat_worker_owner, slot)
                self.assertEqual((process.stdin.close_calls, process.stdout.close_calls), (0, 0))
                self.assertEqual([event for event in process.events if event[0] == "signal"],
                                 [("signal", 15), ("signal", 9)])

    def test_already_reaped_or_missing_group_never_controls_a_numeric_group(self):
        for condition in ("reaped", "missing"):
            with self.subTest(condition=condition):
                process = self.Process([])
                if condition == "reaped":
                    process.returncode = 0
                    process.reaped = True
                else:
                    process._mentat_process_group = None
                slot = self.slot(process)
                with self.posix_effects(process) as control:
                    with self.assertRaises(LinkPreviewWorkerError) as caught:
                        slot.close()
                    with self.assertRaises(LinkPreviewWorkerError):
                        slot.close()
                control.assert_not_called()
                self.assertIs(caught.exception._mentat_worker_owner, slot)
                self.assertIs(slot._process, process)
                self.assertEqual((process.stdin.close_calls, process.stdout.close_calls), (0, 0))

    def test_echild_retains_owner_without_any_signal_or_stream_close(self):
        process = self.Process([])
        slot = self.slot(process)
        error = ChildProcessError("synthetic ownership lost")
        with self.posix_effects(process) as control, \
             mock.patch.object(worker_module.os, "waitid", side_effect=error):
            with self.assertRaises(LinkPreviewWorkerError) as caught:
                slot.close()
        control.assert_not_called()
        self.assertIs(caught.exception.__cause__, error)
        self.assertIs(caught.exception._mentat_worker_owner, slot)
        self.assertIs(slot._process, process)
        self.assertEqual((process.stdin.close_calls, process.stdout.close_calls), (0, 0))

    def test_existing_group_after_reap_never_gets_a_later_cleanup_signal(self):
        events = []
        process = self.Process(events)
        slot = self.slot(process)
        now = [0.0]
        with self.posix_effects(process, group_absent=False) as control, \
             mock.patch.object(worker_module.time, "monotonic", side_effect=lambda: now[0]), \
             mock.patch.object(worker_module.time, "sleep", side_effect=lambda delay: now.__setitem__(0, now[0] + delay)):
            with self.assertRaises(LinkPreviewWorkerError):
                slot.close()
            calls = control.call_count
            with self.assertRaises(LinkPreviewWorkerError):
                slot.close()
            self.assertEqual(control.call_count, calls)
        self.assertTrue(process.reaped)
        self.assertEqual([event for event in events if event[0] == "signal"],
                         [("signal", 15), ("signal", 9)])
        self.assertIs(slot._process, process)

    def test_stream_close_failure_attempts_both_once_and_retains_actual_errors(self):
        for fail in ("before", "after"):
            with self.subTest(fail=fail):
                process = self.Process([], fail=fail)
                slot = self.slot(process)
                with self.posix_effects(process) as control:
                    with self.assertRaises(LinkPreviewWorkerError) as caught:
                        slot.close()
                    calls = control.call_count
                    with self.assertRaises(LinkPreviewWorkerError) as again:
                        slot.close()
                    self.assertEqual(control.call_count, calls)
                self.assertIs(again.exception, caught.exception)
                self.assertEqual((process.stdin.close_calls, process.stdout.close_calls), (1, 1))
                self.assertEqual(process.stdin.closed, fail == "after")
                self.assertTrue(process.stdout.closed)
                self.assertIs(caught.exception._mentat_worker_owner, slot)
                records = slot._cleanup_state["streams"]
                self.assertIs(records[0]["stream"], process.stdin)
                self.assertIs(records[0]["error"], caught.exception.__cause__)
                self.assertIs(slot._process, process)

    def test_windows_keeps_job_handle_control_and_independent_stream_closes(self):
        process = self.Process([], windows=True)
        process._mentat_windows_job = object()
        slot = self.slot(process)
        job = process._mentat_windows_job
        with mock.patch.object(worker_module.os, "name", "nt"), \
             mock.patch.object(worker_module, "_close_windows_job") as close_job, \
             mock.patch.object(worker_module.os, "killpg", create=True) as group:
            slot.close()
            slot.close()
        close_job.assert_called_once_with(job)
        group.assert_not_called()
        self.assertIsNone(process._mentat_windows_job)
        self.assertEqual((process.stdin.close_calls, process.stdout.close_calls), (1, 1))
        self.assertIsNone(slot._process)

    def test_abort_can_finish_while_request_write_remains_blocked(self):
        entered = threading.Event()
        release = threading.Event()
        done = threading.Event()
        process = self.Process([])
        slot = self.slot(process)
        outcomes = []
        probes = [0]
        def health(*_args):
            probes[0] += 1
            return None if probes[0] == 1 else SimpleNamespace(si_pid=process.pid)
        def blocked_write(raw):
            entered.set()
            if not release.wait(timeout=2):
                raise AssertionError("write barrier was not released")
            request = json.loads(raw)
            slot._messages.put_nowait((json.dumps({"type": "result", "id": request["id"],
                                                  "result": {"status": "ready"}}) + "\n").encode())
        process.stdin.on_write = blocked_write
        def execute():
            try:
                outcomes.append(slot.execute(kind="page", url="https://python.org/fixed"))
            except BaseException as error:
                outcomes.append(error)
        def abort():
            try:
                slot.abort()
            except BaseException as error:
                outcomes.append(error)
            finally:
                done.set()
        caller = threading.Thread(target=execute)
        stopper = threading.Thread(target=abort)
        with self.posix_effects(process), mock.patch.object(worker_module.os, "waitid", side_effect=health):
            try:
                caller.start()
                self.assertTrue(entered.wait(timeout=1))
                stopper.start()
                self.assertTrue(done.wait(timeout=1))
                self.assertFalse(release.is_set())
                self.assertTrue(caller.is_alive())
            finally:
                release.set()
                caller.join(timeout=2)
                if stopper.ident is not None:
                    stopper.join(timeout=2)
        self.assertFalse(caller.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertIsNone(slot._process)
        self.assertTrue(all(isinstance(value, LinkPreviewWorkerError) for value in outcomes))

    def test_execute_health_selection_serializes_abort_without_locking_request_io(self):
        entered = threading.Event()
        release = threading.Event()
        abort_started = threading.Event()
        abort_done = threading.Event()
        events = []
        process = self.Process(events)
        slot = self.slot(process)
        outcomes = []
        health_calls = [0]
        class TrackedRLock:
            def __init__(self):
                self.actual = threading.RLock()
                self.owner = None
                self.depth = 0
            def __enter__(self):
                self.actual.acquire()
                self.owner = threading.get_ident()
                self.depth += 1
                return self
            def __exit__(self, *_args):
                self.depth -= 1
                if not self.depth:
                    self.owner = None
                self.actual.release()
        slot._lifecycle_lock = TrackedRLock()
        def health(*_args):
            self.assertEqual(slot._lifecycle_lock.owner, threading.get_ident(),
                             "health observation must hold lifecycle ownership")
            self.assertGreater(slot._lifecycle_lock.depth, 0)
            health_calls[0] += 1
            if health_calls[0] == 1:
                entered.set()
                if not release.wait(timeout=1):
                    raise AssertionError("health barrier was not released")
                return None
            return SimpleNamespace(si_pid=process.pid)
        process.health_hook = health  # Old poll path reaches the same barrier outside the lifecycle lock.
        def respond(raw):
            request = json.loads(raw)
            slot._messages.put_nowait((json.dumps({"type": "result", "id": request["id"],
                                                  "result": {"status": "ready"}}) + "\n").encode())
        process.stdin.on_write = respond
        def execute():
            try:
                outcomes.append(slot.execute(kind="page", url="https://python.org/fixed"))
            except BaseException as error:
                outcomes.append(error)
        def abort():
            abort_started.set()
            try:
                slot.abort()
            except BaseException as error:
                outcomes.append(error)
            finally:
                abort_done.set()
        caller = threading.Thread(target=execute)
        stopper = threading.Thread(target=abort)
        with self.posix_effects(process) as control, \
             mock.patch.object(worker_module.os, "waitid", side_effect=health):
            try:
                caller.start()
                self.assertTrue(entered.wait(timeout=1))
                stopper.start()
                self.assertTrue(abort_started.wait(timeout=1))
                self.assertFalse(abort_done.is_set())
                control.assert_not_called()
            finally:
                release.set()
                caller.join(timeout=2)
                if stopper.ident is not None:
                    stopper.join(timeout=2)
        self.assertFalse(caller.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertTrue(abort_done.is_set())
        self.assertTrue(all(isinstance(value, LinkPreviewWorkerError) or type(value) is dict for value in outcomes))
        self.assertIsNone(slot._process)


if __name__ == "__main__":
    unittest.main()
