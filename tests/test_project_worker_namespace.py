from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from mentat import project_worker_frontend as front
from mentat import project_worker_namespace as namespaces
from mentat import project_worker_scope as scopes


class FrontendContractTests(unittest.TestCase):
    def test_only_one_matching_terminal_and_bounded_text_is_accepted(self):
        terminal = json.dumps({"type": "result", "exit_code": 0, "text": "ok"}).encode()
        self.assertEqual(front.terminal_result(b"inert scanner warning\n" + terminal + b"\n", 0), "ok")
        for output, code in ((terminal + b"\n" + terminal, 0), (terminal, 1),
                             (b'{"type":"result","exit_code":true,"text":"ok"}', 0),
                             (b'{"type":"result","exit_code":0,"text":"x","text":"y"}', 0),
                             (json.dumps({"type": "result", "exit_code": 0, "text": "x" * 32769}).encode(), 0)):
            with self.subTest(code=code), self.assertRaises(front.FrontendError):
                front.terminal_result(output, code)

    def test_large_reply_is_rejected_before_reading_body(self):
        host, worker = socket.socketpair()
        try:
            host.sendall(struct.pack("!I", front.MAX_REPLY + 1))
            with self.assertRaises(front.FrontendError):
                front.exchange(worker, b"{}", time.monotonic() + 1)
        finally:
            host.close()
            worker.close()

    def test_worker_boundary_rejects_paths_tools_nonstream_and_mismatched_models(self):
        host, worker = socket.socketpair()
        service = front.CompletionServer(worker, "mentat-test", time.monotonic() + 10)
        thread = threading.Thread(target=service.serve_forever)
        thread.start()
        try:
            baseline = {"model": "mentat-test", "stream": True, "messages": []}
            for path, body in (("/api/show", baseline), ("/v1/chat/completions?x=1", baseline),
                               ("/v1/chat/completions", {**baseline, "stream": False}),
                               ("/v1/chat/completions", {**baseline, "model": "other"}),
                               ("/v1/chat/completions", {**baseline, "tools": [{"type": "function"}]})):
                client = http.client.HTTPConnection(*service.server_address, timeout=2)
                client.request("POST", path, json.dumps(body))
                reply = client.getresponse()
                self.assertEqual(reply.status, 400)
                reply.read()
                client.close()
            host.setblocking(False)
            with self.assertRaises(BlockingIOError):
                host.recv(1)
        finally:
            service.shutdown()
            service.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            host.close()
            worker.close()

    def test_normalized_reply_becomes_bounded_sse_without_provider_headers(self):
        host, worker = socket.socketpair()
        body = {"model": "mentat-test", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
        seen = []
        def broker():
            amount = struct.unpack("!I", front._read_exact(host, 4))[0]
            seen.append(front._read_exact(host, amount))
            reply = json.dumps({"state": "succeeded", "text": "reply\n"}).encode()
            host.sendall(struct.pack("!I", len(reply)) + reply)
        broker_thread = threading.Thread(target=broker)
        service = front.CompletionServer(worker, "mentat-test", time.monotonic() + 10)
        server_thread = threading.Thread(target=service.serve_forever)
        broker_thread.start()
        server_thread.start()
        try:
            client = http.client.HTTPConnection(*service.server_address, timeout=2)
            raw = json.dumps(body).encode()
            client.request("POST", "/v1/chat/completions", raw, {"Authorization": "dummy-namespace-only"})
            reply = client.getresponse()
            self.assertEqual(reply.status, 200)
            self.assertTrue(reply.read().endswith(b"data: [DONE]\n\n"))
            self.assertEqual(seen, [raw])
            self.assertEqual(service.accepted_text, "reply\n")
            client.close()
        finally:
            service.shutdown()
            service.server_close()
            host.close()
            worker.close()
            server_thread.join(timeout=2)
            broker_thread.join(timeout=2)
            self.assertFalse(server_thread.is_alive() or broker_thread.is_alive())

    def test_unsupported_namespace_fails_before_any_snapshot_or_runtime_open(self):
        with patch.object(namespaces, "IS_LINUX", False), patch.object(namespaces, "_open_directory") as opened:
            with self.assertRaises(scopes.WorkerScopeError):
                namespaces.PreparedNamespace(None, b"query", "0" * 64, "test")
            opened.assert_not_called()

    def test_deadline_and_malformed_reply_do_not_turn_into_known_text(self):
        for reply in ({"state": "succeeded", "text": "ok", "secret_header": "forbidden"},
                      {"state": "unknown", "disposition": "unknown", "text": "no"},
                      {"state": "succeeded", "text": "\u0000"}):
            host, worker = socket.socketpair()
            try:
                encoded = json.dumps(reply).encode()
                host.sendall(struct.pack("!I", len(encoded)) + encoded)
                with self.assertRaises(front.FrontendError):
                    front.exchange(worker, b"{}", time.monotonic() + 1)
            finally:
                host.close()
                worker.close()
        host, worker = socket.socketpair()
        try:
            with self.assertRaises(front.FrontendError):
                front.exchange(worker, b"{}", time.monotonic() - 1)
            host.setblocking(False)
            with self.assertRaises(BlockingIOError):
                host.recv(1)
        finally:
            host.close()
            worker.close()


FAKE_CLI = r'''
import base64, ctypes, http.client, json, os, pathlib, socket, subprocess, sys, time
config = pathlib.Path(os.environ['HERMES_HOME']) / 'fixed.json'
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1] == 'config':
    if sys.argv[2] == 'set':
        values = json.loads(config.read_text()) if config.exists() else {}
        value = sys.argv[4]
        values[sys.argv[3]] = (value == 'true') if value in ('true','false') else int(value) if value.isdigit() else value
        config.write_text(json.dumps(values)); sys.exit(0)
    print(json.dumps(json.loads(config.read_text())[sys.argv[3]])); sys.exit(0)
assert os.environ['HERMES_SAFE_MODE'] == '1'
for path in ('/mnt/c', '/sys/fs/cgroup', '/run/user', '/home/mentat/.hermes/auth.json'):
    assert not os.path.exists(path), path
assert 'NoNewPrivs:\t1' in pathlib.Path('/proc/self/status').read_text()
libc = ctypes.CDLL(None, use_errno=True)
assert libc.unshare(0x10000000) == -1  # Nested userns unavailable.
for path in ('/inputs/query.txt', '/worker/no-write', '/outside'):
    try:
        open(path, 'ab').close(); raise AssertionError('unexpected writable root')
    except OSError: pass
for destination in ('1.1.1.1', '127.0.0.1'):
    endpoint = socket.socket(); endpoint.settimeout(.1)
    try:
        endpoint.connect((destination, 1)); raise AssertionError('unexpected host network')
    except OSError: pass
    finally: endpoint.close()
for path, amount in (('/exports/quota',40*1024*1024),('/tmp/quota',10*1024*1024),('/home/mentat/quota',20*1024*1024)):
    try:
        with open(path,'wb') as stream:
            for _ in range(amount//1048576): stream.write(b'x'*1048576)
        raise AssertionError('quota not enforced')
    except OSError as error: assert error.errno == 28
    finally: pathlib.Path(path).unlink(missing_ok=True)
query = pathlib.Path('/inputs/query.txt').read_text()
if query == 'block':
    subprocess.Popen([sys.executable,'-I','-c','import os,time; os.setsid(); time.sleep(90)'])
    pathlib.Path('/exports/blocked').write_text('ready')
    print('owned child ready',flush=True); time.sleep(90); sys.exit(1)
parts = [{'type':'text','text':query}]
if '--image' in sys.argv:
    path = sys.argv[sys.argv.index('--image')+1]
    parts.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(pathlib.Path(path).read_bytes()).decode()}})
model = sys.argv[sys.argv.index('--model')+1]
body = {'model':model,'stream':True,'tools':[],'messages':[{'role':'user','content':parts}]}
from urllib.parse import urlparse
url = urlparse(os.environ['CUSTOM_BASE_URL'])
connection = http.client.HTTPConnection(url.hostname,url.port,timeout=10)
connection.request('POST','/v1/chat/completions',json.dumps(body))
response = connection.getresponse(); assert response.status == 200
events = response.read().decode(); connection.close()
chunks = [json.loads(line[6:]) for line in events.splitlines() if line.startswith('data: ') and line != 'data: [DONE]']
text = ''.join(chunk['choices'][0]['delta'].get('content','') for chunk in chunks)
print('inert scanner warning',flush=True)
print(json.dumps({'type':'result','exit_code':0,'text':text}),flush=True)
'''


@unittest.skipUnless(scopes.IS_LINUX, "Linux namespace and sealed descriptor tests")
class LinuxNamespaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path("/usr/bin/bwrap").exists() or not Path(f"/run/user/{os.getuid()}/bus").exists():
            raise unittest.SkipTest("Unprivileged namespace/systemd dependencies unavailable")
        if not callable(getattr(os, "memfd_create", None)):
            raise unittest.SkipTest("Sealed snapshots unavailable")
        cls.python_root = Path(sys.base_prefix).resolve()
        # Actual supported qualification uses a complete private Python runtime;
        # standard /usr installations need a separate reviewed layout.
        if len(cls.python_root.parts) < 3:
            raise unittest.SkipTest("Separate pinned Python runtime unavailable")

    def _roots(self, root):
        source, venv = root / "source", root / "venv"
        (source / "hermes_cli").mkdir(parents=True)
        (source / "hermes_cli/main.py").write_text("# inert synthetic runtime\n")
        (venv / "bin").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = " + str(self.python_root / "bin") + "\ninclude-system-site-packages = false\n")
        (venv / "bin/python").symlink_to(Path(sys.executable).resolve())
        cli = venv / "bin/hermes"
        cli.write_text("#!" + str(Path(sys.executable).resolve()) + "\n" + FAKE_CLI)
        cli.chmod(0o700)
        return namespaces.RuntimeRoots(source, venv, self.python_root)

    def _run(self, roots, query=b"synthetic query", *, image=None):
        prepared = namespaces.PreparedNamespace(roots, query, hashlib.sha256(query).hexdigest(),
                    "mentat-test", vision=image is not None, image=image,
                    image_digest=hashlib.sha256(image).hexdigest() if image else None,
                    image_extension=".png" if image else "")
        try:
            scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=30))
            broker, worker = socket.socketpair()
        except BaseException:
            prepared.close()
            raise
        seen, errors = [], []
        broker.settimeout(30)
        def serve():
            try:
                amount = struct.unpack("!I", front._read_exact(broker, 4))[0]
                self.assertLessEqual(amount, front.MAX_REQUEST)
                seen.append(json.loads(front._read_exact(broker, amount)))
                answer = json.dumps({"state": "succeeded", "text": "PROBE_OK"}).encode()
                broker.sendall(struct.pack("!I", len(answer)) + answer)
            except Exception as error:
                errors.append(type(error).__name__)
        thread = threading.Thread(target=serve)
        try:
            scope.start_inert()
            thread.start()
            handle = scope.handoff_namespace(prepared, worker)
            result = handle.wait()
            self.assertEqual(result["text"], "PROBE_OK")
            self.assertTrue(scope._empty())
            descriptor = os.open("completion.txt", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=handle.exports_descriptor)
            with os.fdopen(descriptor, "rb") as stream:
                self.assertEqual(stream.read(100), b"PROBE_OK")
            return seen
        finally:
            try:
                scope.close_verified()
            finally:
                for endpoint in (worker, broker):
                    try:
                        endpoint.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    endpoint.close()
                if thread.ident is not None:
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())
                prepared.close()
            self.assertFalse(errors)

    def test_fixed_namespace_handoff_enforces_files_network_and_quotas(self):
        with TemporaryDirectory(prefix="mentat-namespace-test-") as temporary:
            roots = self._roots(Path(temporary))
            seen = self._run(roots)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]["tools"], [])

    def test_native_image_bytes_and_export_descriptor_survive_worker_exit(self):
        with TemporaryDirectory(prefix="mentat-namespace-image-") as temporary:
            image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
            seen = self._run(self._roots(Path(temporary)), image=image)
            native = seen[0]["messages"][0]["content"][1]["image_url"]["url"]
            self.assertEqual(base64.b64decode(native.split(",", 1)[1], validate=True), image)

    def test_pinned_snapshots_are_sealed_and_directory_symlink_is_rejected(self):
        with TemporaryDirectory(prefix="mentat-namespace-pin-") as temporary:
            root = Path(temporary)
            roots = self._roots(root)
            query = b"exact bytes"
            prepared = namespaces.PreparedNamespace(roots, query, hashlib.sha256(query).hexdigest(), "test")
            try:
                with self.assertRaises(OSError):
                    os.write(prepared._fds[5], b"changed")
                with self.assertRaises(OSError):
                    os.ftruncate(prepared._fds[5], 0)
            finally:
                prepared.close()
            link = root / "redirect"
            link.symlink_to(roots.source)
            with self.assertRaises(OSError):
                namespaces.PreparedNamespace(namespaces.RuntimeRoots(link, roots.venv, roots.python),
                                             query, hashlib.sha256(query).hexdigest(), "test")

    def test_owned_scope_stop_removes_blocked_namespace_and_detached_descendant(self):
        with TemporaryDirectory(prefix="mentat-namespace-stop-") as temporary:
            prepared = namespaces.PreparedNamespace(self._roots(Path(temporary)), b"block",
                                                     hashlib.sha256(b"block").hexdigest(), "test")
            scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=20))
            broker, worker = socket.socketpair()
            try:
                scope.start_inert()
                handle = scope.handoff_namespace(prepared, worker)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        descriptor = os.open("blocked", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=handle.exports_descriptor)
                        os.close(descriptor)
                        break
                    except FileNotFoundError:
                        if time.monotonic() >= deadline:
                            self.fail("Disposable detached child did not reach stop gate")
                        time.sleep(.02)
                members = scopes._read_control(scope._descriptor, "cgroup.procs").splitlines()
                self.assertGreaterEqual(len(members), 5)
                self.assertTrue(scope.stop_local_and_verify())
                self.assertTrue(scope._empty())
                self.assertIsNotNone(scope._process.returncode)
                broker.setblocking(False)
                with self.assertRaises(BlockingIOError):
                    broker.recv(1)  # No completion call escaped before Stop.
            finally:
                scope.close_verified()
                broker.close()
                worker.close()
                prepared.close()

    def test_ambiguous_handoff_cannot_be_repeated(self):
        with TemporaryDirectory(prefix="mentat-namespace-once-") as temporary:
            query = b"test"
            prepared = namespaces.PreparedNamespace(self._roots(Path(temporary)), query,
                                                     hashlib.sha256(query).hexdigest(), "test")
            scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=10))
            broker, worker = socket.socketpair()
            try:
                scope.start_inert()
                with patch.object(prepared, "handoff", side_effect=OSError("controlled after reservation")):
                    with self.assertRaises(OSError):
                        scope.handoff_namespace(prepared, worker)
                self.assertTrue(scope._namespace_handed_off)
                with patch.object(prepared, "handoff") as handoff, self.assertRaises(scopes.WorkerScopeError):
                    scope.handoff_namespace(prepared, worker)
                handoff.assert_not_called()
            finally:
                scope.close_verified()
                broker.close()
                worker.close()
                prepared.close()

    def test_combined_child_output_and_wall_are_bounded(self):
        original = subprocess.Popen
        children = []
        with TemporaryDirectory(prefix="mentat-output-test-") as temporary:
            def launch(command, **kwargs):
                kwargs["cwd"] = temporary
                child = original(command, **kwargs)
                children.append(child)
                return child
            with patch.object(front.subprocess, "Popen", side_effect=launch):
                for code, deadline in (("import os; os.write(1,b'x'*600000)", time.monotonic() + 5),
                                       ("import time; time.sleep(30)", time.monotonic() + .15)):
                    with self.assertRaises(front.FrontendError):
                        front.run_bounded([sys.executable, "-I", "-c", code],
                                          {"PATH": "/usr/bin:/bin"}, deadline)
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertTrue(all(child.stdout.closed and child.stderr.closed for child in children))

    def test_expired_buffered_terminal_never_wins_watchdog_race(self):
        packet = json.dumps({"version": 1, "kind": "terminal", "exit_code": 0,
                             "text": "ok", "output_bytes": 100}).encode()
        for clock in ([101], [99, 101], [99, 99, 99, 101], [99, 99, 99, 99, 101]):
            scope = MagicMock()
            scope._deadline, scope.deadline_hit, scope._process.returncode = 100, False, 0
            scope._control.recv.return_value = b"EXIT 0\n"
            scope.stop_local_and_verify.return_value = True
            lifecycle = MagicMock()
            lifecycle.recvmsg.return_value = (packet, [], 0, None)
            handle = namespaces.NamespaceWorker(scope, lifecycle, 9999)
            with self.subTest(clock=clock), patch.object(namespaces.time, "monotonic", side_effect=clock), self.assertRaises(
                scopes.WorkerScopeError
            ):
                handle.wait()
            if clock == [101]:
                lifecycle.recvmsg.assert_not_called()

    def test_expired_readiness_closes_transferred_descriptor(self):
        import array
        with TemporaryDirectory(prefix="mentat-ready-expiry-") as temporary:
            descriptor = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY)
            endpoint = MagicMock()
            endpoint.recvmsg.return_value = (b'{"version":1,"kind":"ready"}',
                    [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [descriptor]).tobytes())], 0, None)
            with patch.object(namespaces.time, "monotonic", side_effect=[99, 101]), self.assertRaises(scopes.WorkerScopeError):
                namespaces.receive_ready(endpoint, 100)
            with self.assertRaises(OSError):
                os.fstat(descriptor)
            endpoint = MagicMock()
            with patch.object(namespaces.time, "monotonic", return_value=101), self.assertRaises(scopes.WorkerScopeError):
                namespaces.receive_ready(endpoint, 100)
            endpoint.recvmsg.assert_not_called()

    def test_malformed_ancillary_order_and_truncation_close_every_owned_descriptor(self):
        import array
        for method, packet in ((namespaces.receive_handoff, b"invalid"),
                               (lambda endpoint: namespaces.receive_ready(endpoint, time.monotonic() + 2),
                                b'{"version":1,"kind":"ready"}')):
            for unexpected, flags in ((True, 0), (False, socket.MSG_CTRUNC), (False, socket.MSG_TRUNC)):
                reader, writer = os.pipe()
                os.close(writer)
                endpoint = MagicMock()
                ancillary = [(999, 999, b"unexpected")] if unexpected else []
                ancillary += [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [reader]).tobytes())]
                endpoint.recvmsg.return_value = (packet, ancillary, flags, None)
                with self.subTest(method=method, flags=flags), self.assertRaises(scopes.WorkerScopeError):
                    method(endpoint)
                with self.assertRaises(OSError):
                    os.fstat(reader)

    def test_changed_kernel_limits_refuse_handoff_before_any_descriptor_send(self):
        with TemporaryDirectory(prefix="mentat-namespace-limits-") as temporary:
            query = b"test"
            prepared = namespaces.PreparedNamespace(self._roots(Path(temporary)), query,
                                                     hashlib.sha256(query).hexdigest(), "test")
            scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=10))
            broker, worker = socket.socketpair()
            try:
                scope.start_inert()
                with patch.object(scopes, "_effective_limits", side_effect=scopes.WorkerScopeError("changed limits")), patch.object(
                    prepared, "handoff"
                ) as handoff, self.assertRaises(scopes.WorkerScopeError):
                    scope.handoff_namespace(prepared, worker)
                handoff.assert_not_called()
                self.assertFalse(scope._namespace_handed_off)
            finally:
                scope.close_verified()
                broker.close()
                worker.close()
                prepared.close()

    def test_unchanged_stock_cli_reaches_only_fake_broker(self):
        values = [os.environ.get(key) for key in ("MENTAT_TEST_HERMES_SOURCE", "MENTAT_TEST_HERMES_VENV", "MENTAT_TEST_PYTHON_ROOT")]
        if not all(values):
            self.skipTest("Operator-supplied pinned official stock installation unavailable")
        roots = namespaces.RuntimeRoots(*(Path(value) for value in values))
        image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==")
        seen = self._run(roots, b"Reply with PROBE_OK exactly.", image=image)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].get("tools") or [], [])
        messages = seen[0]["messages"]
        urls = [part["image_url"]["url"] for message in messages for part in
                (message.get("content") if isinstance(message.get("content"), list) else [])
                if part.get("type") == "image_url"]
        self.assertEqual(len(urls), 1)
        self.assertEqual(base64.b64decode(urls[0].split(",", 1)[1], validate=True), image)


if __name__ == "__main__":
    unittest.main()
