import json
import os
from pathlib import Path
import ssl
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from data_backup_restore import create_durable_backup
import json_store
from private_state import (
    CONNECTION_SERVER_RESERVATION_NAME,
    mentat_server_active,
    private_state_lock,
    release_mentat_server,
    reserve_mentat_server,
)
import remote_hermes
import runtime_config
import server


DISTINCTIVE_SECRET = "remote-test-key-NEVER-RETURN-12345"


def _health(*, status="ok", version="0.18.2"):
    return {
        "status": status,
        "platform": "hermes-agent",
        "version": version,
        "readiness": {
            "status": status,
            "checks": {
                "config": {"status": "ok", "detail": DISTINCTIVE_SECRET},
                "gateway": {"status": status, "state": "running"},
            },
        },
        "pid": 123,
        "platforms": {"private-platform": {"token": DISTINCTIVE_SECRET}},
    }


def _capabilities(*, auth_required=True, model="anthropic/claude-test"):
    return {
        "object": "hermes.api_server.capabilities",
        "platform": "hermes-agent",
        "model": model,
        "auth": {"type": "bearer", "required": auth_required},
        "runtime": {
            "mode": "server_agent",
            "tool_execution": "server",
            "split_runtime": False,
            "description": DISTINCTIVE_SECRET,
        },
        "features": {
            "chat_completions": True,
            "run_submission": True,
            "admin_config_rw": False,
            "future_secret_feature": DISTINCTIVE_SECRET,
            "session_continuity_header": "X-Hermes-Session-Id",
        },
        "endpoints": {
            "health": {"method": "GET", "path": "/health"},
            "health_detailed": {"method": "GET", "path": "/health/detailed"},
            "runs": {"method": "POST", "path": "/v1/runs"},
            "future": {"method": "POST", "path": f"/{DISTINCTIVE_SECRET}"},
        },
    }


class FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status = status
        self.raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(self.raw))}
        self.headers.update(headers or {})

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, amount):
        return self.raw[:amount]


class FakeConnection:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls
        self.closed = False

    def request(self, method, path, headers=None):
        self.calls.append({"method": method, "path": path, "headers": dict(headers or {})})

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class ResponseQueue:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.connections = []
        self.parameters = []

    def __call__(self, scheme, host, port, timeout):
        self.parameters.append((scheme, host, port, timeout))
        connection = FakeConnection(self.responses.pop(0), self.calls)
        self.connections.append(connection)
        return connection


class FakeDiscoveryClient:
    calls = []

    def __init__(self, endpoint, api_key):
        self.endpoint = endpoint
        self.api_key = api_key
        self.__class__.calls.append((endpoint, api_key))

    def discover(self):
        return {
            "status": "healthy",
            "liveness": "ok",
            "trusted": True,
            "platform": "hermes-agent",
            "version": "0.18.2",
            "model": "anthropic/claude-test",
            "readiness": {"config": "ok"},
            "capabilities": ["chat_completions"],
        }


class DegradedDiscoveryClient(FakeDiscoveryClient):
    def discover(self):
        payload = super().discover()
        payload["status"] = "degraded"
        payload["readiness"] = {"config": "ok", "gateway": "degraded"}
        return payload


class RemoteHermesTests(unittest.TestCase):
    def setUp(self):
        FakeDiscoveryClient.calls = []
        with remote_hermes._PREVIEW_LOCK:
            remote_hermes._PREVIEW_GRANTS.clear()

    def _root(self, temporary):
        root = Path(temporary) / "operator-data"
        root.mkdir(mode=0o700)
        if os.name == "posix":
            root.chmod(0o700)
        return root

    def _owner_only(self, path: Path, *, directory: bool) -> None:
        if os.name == "nt":
            remote_hermes._windows_set_owner_only(path, directory=directory)
        else:
            path.chmod(0o700 if directory else 0o600)

    def _remote_payload(self, **updates):
        payload = {
            "mode": "remote",
            "label": "Workshop Hermes",
            "endpoint": "https://Hermes.Example:443/",
            "api_key": DISTINCTIVE_SECRET,
        }
        payload.update(updates)
        return payload

    def _confirm(self, root, payload=None):
        selected = payload or self._remote_payload()
        preview = remote_hermes.preview_connection(root, selected)
        return remote_hermes.confirm_connection(
            root,
            selected,
            preview.confirmation_token,
            client_factory=FakeDiscoveryClient,
        )

    def test_endpoint_validation_normalizes_one_origin_and_rejects_injection(self):
        accepted = {
            "https://Hermes.Example:443/": "https://hermes.example",
            "https://example.com:8443": "https://example.com:8443",
            "http://127.0.0.1:8642/": "http://127.0.0.1:8642",
            "http://[::1]:8642": "http://[::1]:8642",
            "https://bücher.example": "https://xn--bcher-kva.example",
        }
        for value, expected in accepted.items():
            with self.subTest(value=value):
                self.assertEqual(remote_hermes.normalize_endpoint(value), expected)

        rejected = (
            "http://hermes.example",
            "http://localhost:8642",
            "ftp://hermes.example",
            "https://user:pass@hermes.example",
            "https://hermes.example/api",
            "https://hermes.example?api_key=secret",
            "https://hermes.example?",
            "https://hermes.example#fragment",
            "https://hermes.example#",
            "https://hermes.example/?",
            "https://hermes.example/#",
            "https://hermes.example:0",
            "https://hermes.example:99999",
            "https://example.com.",
            "https://bad_host.example",
            "https://-bad.example",
            "https://bad-.example",
            "https://bad host.example",
            "https://bad\nhost.example",
            "https://[fe80::1%25en0]",
            " https://hermes.example",
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(remote_hermes.RemoteHermesError):
                    remote_hermes.normalize_endpoint(value)

    def test_json_wrong_types_return_bounded_validation_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            cases = (
                {"mode": [], "label": "Local", "endpoint": None, "api_key": None},
                {"mode": "local", "label": "Local", "endpoint": [], "api_key": None},
                {"mode": "local", "label": "Local", "endpoint": None, "api_key": {}},
                {"mode": "remote", "label": "Remote", "endpoint": [], "api_key": DISTINCTIVE_SECRET},
                {"mode": "remote", "label": "Remote", "endpoint": "https://hermes.example", "api_key": []},
            )
            with patch.object(server, "DATA_DIR", root):
                for payload in cases:
                    with self.subTest(payload=payload):
                        response, status = server.preview_hermes_connection(payload)
                        self.assertEqual(status, 400)
                        self.assertIn("error_code", response)

    def test_missing_record_defaults_local_without_creating_private_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            selected = remote_hermes.load_connection(root)
            self.assertEqual(selected.mode, "local")
            self.assertEqual(selected.binding_id, "local-default")
            self.assertFalse((root / "private").exists())

    def test_missing_record_read_serializes_with_first_remote_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            started = threading.Event()
            result = []

            def read_selection():
                started.set()
                result.append(remote_hermes.load_connection(root))

            with private_state_lock(root):
                worker = threading.Thread(target=read_selection)
                worker.start()
                self.assertTrue(started.wait(timeout=1))
                self.assertTrue(worker.is_alive())
                self._confirm(root)
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result[0].mode, "remote")

    def test_confirm_separates_owner_only_secret_from_connection_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            result = self._confirm(root)
            path = remote_hermes.connection_path(root)
            credential_path = remote_hermes.connection_credential_path(root)
            self.assertTrue(path.is_file())
            self.assertTrue(credential_path.is_file())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(credential_path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn(DISTINCTIVE_SECRET, raw)
            self.assertIn(DISTINCTIVE_SECRET, credential_path.read_text(encoding="utf-8"))
            self.assertIn('"schema_version": 2', raw)
            self.assertIn('"kind": "private_env_file"', raw)
            self.assertNotIn(DISTINCTIVE_SECRET, json.dumps(result))
            self.assertNotIn("endpoint", result["selection"])
            selected = remote_hermes.load_connection(root)
            self.assertEqual(selected.endpoint, "https://hermes.example")
            self.assertEqual(selected.api_key, DISTINCTIVE_SECRET)
            self.assertRegex(selected.binding_id, r"^[0-9a-f]{32}$")

    def test_preview_does_not_echo_secret_or_endpoint_and_confirmation_is_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            payload = self._remote_payload()
            preview = remote_hermes.preview_connection(root, payload)
            public = json.dumps(preview.public_summary())
            self.assertNotIn(DISTINCTIVE_SECRET, public)
            self.assertNotIn("hermes.example", public)
            self.assertNotIn("fingerprint", public)
            with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "connection_confirmation_invalid"):
                remote_hermes.confirm_connection(
                    root,
                    {**payload, "api_key": DISTINCTIVE_SECRET + "-changed"},
                    preview.confirmation_token,
                    client_factory=FakeDiscoveryClient,
                )
            self.assertFalse(remote_hermes.connection_path(root).exists())

            for private_label in (
                "hermes.example",
                "https://hermes.example workspace",
            ):
                with self.subTest(private_label=private_label):
                    with self.assertRaisesRegex(
                        remote_hermes.RemoteHermesError,
                        "connection_label_private_shaped",
                    ):
                        remote_hermes.preview_connection(
                            root,
                            {**payload, "label": private_label},
                        )

    def test_confirmation_token_is_single_use_even_for_unchanged_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            local = {
                "mode": "local",
                "label": "Local Hermes",
                "endpoint": None,
                "api_key": None,
            }
            preview = remote_hermes.preview_connection(root, local)
            first = remote_hermes.confirm_connection(
                root,
                local,
                preview.confirmation_token,
                client_factory=FakeDiscoveryClient,
            )
            self.assertEqual(first["status"], "selected")
            with self.assertRaisesRegex(
                remote_hermes.RemoteHermesError,
                "connection_confirmation_invalid",
            ):
                remote_hermes.confirm_connection(
                    root,
                    local,
                    preview.confirmation_token,
                    client_factory=FakeDiscoveryClient,
                )

    def test_changed_record_invalidates_preview_after_remote_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            initial = self._remote_payload(label="Initial")
            stale = remote_hermes.preview_connection(root, initial)
            self._confirm(root, self._remote_payload(label="Concurrent"))
            with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "connection_confirmation_invalid"):
                remote_hermes.confirm_connection(
                    root,
                    initial,
                    stale.confirmation_token,
                    client_factory=FakeDiscoveryClient,
                )
            self.assertEqual(remote_hermes.load_connection(root).label, "Concurrent")

    def test_record_change_during_probe_invalidates_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            requested = self._remote_payload(label="Requested")
            preview = remote_hermes.preview_connection(root, requested)

            class RacingClient:
                def __init__(self, _endpoint, _api_key):
                    pass

                def discover(self):
                    self_outer._confirm(root, self_outer._remote_payload(label="Concurrent"))
                    return FakeDiscoveryClient("https://unused.example", DISTINCTIVE_SECRET).discover()

            self_outer = self
            with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "connection_changed"):
                remote_hermes.confirm_connection(
                    root,
                    requested,
                    preview.confirmation_token,
                    client_factory=RacingClient,
                )
            self.assertEqual(remote_hermes.load_connection(root).label, "Concurrent")

    def test_selected_connection_probe_rejects_binding_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            self._confirm(root, self._remote_payload(label="Initial"))

            class RacingClient:
                def __init__(self, _endpoint, _api_key):
                    pass

                def discover(self):
                    self_outer._confirm(
                        root,
                        self_outer._remote_payload(
                            label="Concurrent",
                            api_key=DISTINCTIVE_SECRET + "-rotated",
                        ),
                    )
                    return FakeDiscoveryClient(
                        "https://unused.example",
                        DISTINCTIVE_SECRET,
                    ).discover()

            self_outer = self
            with self.assertRaisesRegex(
                remote_hermes.RemoteHermesError,
                "connection_changed",
            ):
                remote_hermes.test_selected_connection(
                    root,
                    client_factory=RacingClient,
                )
            self.assertEqual(remote_hermes.load_connection(root).label, "Concurrent")

    def test_probe_failure_and_verified_rollback_preserve_previous_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            initial_payload = self._remote_payload(label="Initial")
            self._confirm(root, initial_payload)
            path = remote_hermes.connection_path(root)
            before = path.read_bytes()

            class ProbeFailure:
                def __init__(self, _endpoint, _api_key):
                    pass

                def discover(self):
                    raise remote_hermes.RemoteHermesError("remote_timeout")

            changed = self._remote_payload(label="Changed")
            preview = remote_hermes.preview_connection(root, changed)
            with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_timeout"):
                remote_hermes.confirm_connection(
                    root,
                    changed,
                    preview.confirmation_token,
                    client_factory=ProbeFailure,
                )
            self.assertEqual(path.read_bytes(), before)

            preview = remote_hermes.preview_connection(root, changed)
            real_write = remote_hermes.write_json_atomic
            calls = []

            def fail_after_first_commit(*args, **kwargs):
                calls.append(1)
                real_write(*args, **kwargs)
                if len(calls) == 1:
                    raise OSError("simulated post-commit verification failure")

            with patch.object(remote_hermes, "write_json_atomic", side_effect=fail_after_first_commit):
                with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "connection_commit_rolled_back"):
                    remote_hermes.confirm_connection(
                        root,
                        changed,
                        preview.confirmation_token,
                        client_factory=FakeDiscoveryClient,
                    )
            self.assertEqual(len(calls), 2)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(remote_hermes.load_connection(root).label, "Initial")

    def test_private_directory_swap_cannot_escape_connection_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            payload = self._remote_payload()
            preview = remote_hermes.preview_connection(root, payload)
            private = root / "private"
            displaced = root / "private-displaced"
            outside = Path(temporary) / "outside"
            outside.mkdir(mode=0o700)
            real_write = remote_hermes.write_json_atomic

            def swap_before_write(*args, **kwargs):
                private.rename(displaced)
                private.symlink_to(outside, target_is_directory=True)
                return real_write(*args, **kwargs)

            with patch.object(
                remote_hermes,
                "write_json_atomic",
                side_effect=swap_before_write,
            ):
                with self.assertRaises(remote_hermes.RemoteHermesError):
                    remote_hermes.confirm_connection(
                        root,
                        payload,
                        preview.confirmation_token,
                        client_factory=FakeDiscoveryClient,
                    )

            for candidate in (
                displaced / remote_hermes.CONNECTION_FILE_NAME,
                outside / remote_hermes.CONNECTION_FILE_NAME,
            ):
                self.assertFalse(candidate.exists())
            self.assertNotIn(
                DISTINCTIVE_SECRET,
                "\n".join(
                    path.read_text(encoding="utf-8", errors="replace")
                    for directory in (displaced, outside)
                    if directory.exists()
                    for path in directory.rglob("*")
                    if path.is_file()
                ),
            )

    def test_connection_changes_rotate_binding_and_local_switch_does_not_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            first = self._confirm(root)["selection"]["binding_id"]
            changed_payload = self._remote_payload(api_key=DISTINCTIVE_SECRET + "-rotated")
            second = self._confirm(root, changed_payload)["selection"]["binding_id"]
            self.assertNotEqual(first, second)
            calls_before = list(FakeDiscoveryClient.calls)
            local = {"mode": "local", "label": "Local Hermes", "endpoint": None, "api_key": None}
            preview = remote_hermes.preview_connection(root, local)
            result = remote_hermes.confirm_connection(
                root,
                local,
                preview.confirmation_token,
                client_factory=FakeDiscoveryClient,
            )
            self.assertEqual(result["selection"]["mode"], "local")
            self.assertNotEqual(second, result["selection"]["binding_id"])
            self.assertEqual(FakeDiscoveryClient.calls, calls_before)

    def test_local_selection_retains_and_retests_one_remembered_remote(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            remote_binding = self._confirm(root)["selection"]["binding_id"]
            local_preview = remote_hermes.preview_remembered_connection(root, "local")
            local = remote_hermes.confirm_remembered_connection(
                root,
                "local",
                local_preview.confirmation_token,
                client_factory=FakeDiscoveryClient,
            )
            state = remote_hermes.load_connection_state(root)
            self.assertEqual(local["selection"]["mode"], "local")
            self.assertIsNotNone(state.remote)
            self.assertEqual(state.remote.label, "Workshop Hermes")
            self.assertNotEqual(local["selection"]["binding_id"], remote_binding)

            calls_before = len(FakeDiscoveryClient.calls)
            tested = remote_hermes.test_connection_mode(
                root,
                "remote",
                client_factory=FakeDiscoveryClient,
            )
            self.assertEqual(tested["status"], "verified")
            self.assertEqual(remote_hermes.load_connection(root).mode, "local")
            self.assertEqual(len(FakeDiscoveryClient.calls), calls_before + 1)

            remote_preview = remote_hermes.preview_remembered_connection(root, "remote")
            selected = remote_hermes.confirm_remembered_connection(
                root,
                "remote",
                remote_preview.confirmation_token,
                client_factory=FakeDiscoveryClient,
            )
            self.assertEqual(selected["selection"]["mode"], "remote")
            self.assertEqual(
                remote_hermes.load_connection(root).endpoint,
                "https://hermes.example",
            )

    def test_environment_and_owner_only_env_file_sources_are_resolved_server_side(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            with patch.dict(
                os.environ,
                {"MENTAT_REMOTE_HERMES_API_KEY": DISTINCTIVE_SECRET},
            ):
                source = remote_hermes.credential_source_from_values(
                    "environment",
                    name="MENTAT_REMOTE_HERMES_API_KEY",
                )
                preview = remote_hermes.preview_connection_from_source(
                    root,
                    label="Environment remote",
                    endpoint="https://hermes.example",
                    credential_source=source,
                )
                result = remote_hermes.confirm_connection_from_source(
                    root,
                    label="Environment remote",
                    endpoint="https://hermes.example",
                    credential_source=source,
                    confirmation_token=preview.confirmation_token,
                    client_factory=FakeDiscoveryClient,
                )
            self.assertEqual(result["selection"]["mode"], "remote")
            record = remote_hermes.connection_path(root).read_text(encoding="utf-8")
            self.assertNotIn(DISTINCTIVE_SECRET, record)
            self.assertIn('"kind": "environment"', record)

            env_file = Path(temporary) / "remote.env"
            env_file.write_text(
                f"MENTAT_REMOTE_HERMES_API_KEY={json.dumps(DISTINCTIVE_SECRET)}\n",
                encoding="utf-8",
            )
            self._owner_only(env_file, directory=False)
            file_source = remote_hermes.credential_source_from_values(
                "env_file",
                path=str(env_file),
            )
            preview = remote_hermes.preview_connection_from_source(
                root,
                label="File remote",
                endpoint="https://hermes.example",
                credential_source=file_source,
            )
            result = remote_hermes.confirm_connection_from_source(
                root,
                label="File remote",
                endpoint="https://hermes.example",
                credential_source=file_source,
                confirmation_token=preview.confirmation_token,
                client_factory=FakeDiscoveryClient,
            )
            self.assertEqual(result["selection"]["label"], "File remote")
            self.assertNotIn(str(env_file), json.dumps(result))
            self.assertNotIn(DISTINCTIVE_SECRET, json.dumps(result))

    def test_unsafe_missing_or_malformed_env_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            source_path = Path(temporary) / "remote.env"
            source = remote_hermes.credential_source_from_values(
                "env_file",
                path=str(source_path),
            )
            cases = ("missing", "broad", "symlink", "malformed")
            for case in cases:
                with self.subTest(case=case):
                    source_path.unlink(missing_ok=True)
                    target = Path(temporary) / "target.env"
                    target.unlink(missing_ok=True)
                    if case == "broad":
                        source_path.write_text(
                            f"MENTAT_REMOTE_HERMES_API_KEY={DISTINCTIVE_SECRET}\n",
                            encoding="utf-8",
                        )
                        source_path.chmod(0o644)
                    elif case == "symlink":
                        target.write_text(
                            f"MENTAT_REMOTE_HERMES_API_KEY={DISTINCTIVE_SECRET}\n",
                            encoding="utf-8",
                        )
                        target.chmod(0o600)
                        source_path.symlink_to(target)
                    elif case == "malformed":
                        source_path.write_text(
                            "MENTAT_REMOTE_HERMES_API_KEY=too short\n",
                            encoding="utf-8",
                        )
                        source_path.chmod(0o600)
                    with self.assertRaises(remote_hermes.RemoteHermesError):
                        remote_hermes.preview_connection_from_source(
                            root,
                            label="Remote",
                            endpoint="https://hermes.example",
                            credential_source=source,
                        )
                    self.assertEqual(
                        remote_hermes.load_connection_state(root).mode,
                        "local",
                    )

    def test_schema_v1_remote_migrates_key_to_private_env_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            private = root / "private"
            private.mkdir(mode=0o700)
            self._owner_only(private, directory=True)
            path = remote_hermes.connection_path(root)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "mode": "remote",
                        "label": "Legacy remote",
                        "binding_id": "a" * 32,
                        "endpoint": "https://hermes.example",
                        "api_key": DISTINCTIVE_SECRET,
                    }
                ),
                encoding="utf-8",
            )
            self._owner_only(path, directory=False)
            selected = remote_hermes.load_connection(root)
            self.assertEqual(selected.mode, "remote")
            self.assertEqual(selected.api_key, DISTINCTIVE_SECRET)
            record = path.read_text(encoding="utf-8")
            credential = remote_hermes.connection_credential_path(root)
            self.assertIn('"schema_version": 2', record)
            self.assertNotIn(DISTINCTIVE_SECRET, record)
            self.assertIn(
                DISTINCTIVE_SECRET,
                credential.read_text(encoding="utf-8"),
            )
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(credential.stat().st_mode), 0o600)

    def test_server_first_reservation_blocks_inflight_offline_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            payload = self._remote_payload()
            preview = remote_hermes.preview_connection(root, payload)
            reservation_written = threading.Event()
            allow_reservation_commit = threading.Event()
            reserve_errors = []
            confirm_errors = []
            original_write = json_store.write_json_atomic

            def blocking_reservation_write(path, *args, **kwargs):
                result = original_write(path, *args, **kwargs)
                if Path(path).name == CONNECTION_SERVER_RESERVATION_NAME:
                    reservation_written.set()
                    self.assertTrue(allow_reservation_commit.wait(timeout=2))
                return result

            def reserve():
                try:
                    reserve_mentat_server(root)
                except Exception as exc:
                    reserve_errors.append(exc)

            def confirm():
                try:
                    remote_hermes.confirm_connection(
                        root,
                        payload,
                        preview.confirmation_token,
                        require_server_stopped=True,
                        client_factory=FakeDiscoveryClient,
                    )
                except Exception as exc:
                    confirm_errors.append(exc)

            with patch.object(
                json_store,
                "write_json_atomic",
                side_effect=blocking_reservation_write,
            ):
                reserve_thread = threading.Thread(target=reserve)
                reserve_thread.start()
                self.assertTrue(reservation_written.wait(timeout=2))
                confirm_thread = threading.Thread(target=confirm)
                confirm_thread.start()
                self.assertTrue(confirm_thread.is_alive())
                allow_reservation_commit.set()
                reserve_thread.join(timeout=2)
                confirm_thread.join(timeout=2)
            try:
                self.assertFalse(reserve_errors)
                self.assertEqual(len(confirm_errors), 1)
                self.assertIsInstance(
                    confirm_errors[0],
                    remote_hermes.RemoteHermesError,
                )
                self.assertEqual(
                    confirm_errors[0].code,
                    "connection_change_server_running",
                )
                self.assertTrue(mentat_server_active(root))
                self.assertEqual(remote_hermes.load_connection_state(root).mode, "local")
            finally:
                release_mentat_server(root)

    def test_mutation_first_commit_finishes_before_startup_reservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            payload = self._remote_payload()
            preview = remote_hermes.preview_connection(root, payload)
            mutation_holds_lock = threading.Event()
            allow_mutation_commit = threading.Event()
            confirm_results = []
            errors = []

            def paused_server_check(_root):
                mutation_holds_lock.set()
                self.assertTrue(allow_mutation_commit.wait(timeout=2))
                return False

            def confirm():
                try:
                    confirm_results.append(
                        remote_hermes.confirm_connection(
                            root,
                            payload,
                            preview.confirmation_token,
                            require_server_stopped=True,
                            client_factory=FakeDiscoveryClient,
                        )
                    )
                except Exception as exc:
                    errors.append(exc)

            def reserve():
                try:
                    reserve_mentat_server(root)
                except Exception as exc:
                    errors.append(exc)

            with patch.object(
                remote_hermes,
                "mentat_server_active",
                side_effect=paused_server_check,
            ):
                confirm_thread = threading.Thread(target=confirm)
                confirm_thread.start()
                self.assertTrue(mutation_holds_lock.wait(timeout=2))
                reserve_thread = threading.Thread(target=reserve)
                reserve_thread.start()
                self.assertTrue(reserve_thread.is_alive())
                allow_mutation_commit.set()
                confirm_thread.join(timeout=2)
                reserve_thread.join(timeout=2)
            try:
                self.assertFalse(errors)
                self.assertEqual(
                    confirm_results[0]["selection"]["mode"],
                    "remote",
                )
                self.assertEqual(remote_hermes.load_connection(root).mode, "remote")
                self.assertTrue(mentat_server_active(root))
            finally:
                release_mentat_server(root)

    def test_live_server_blocks_automatic_schema_v1_migration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            private = root / "private"
            private.mkdir(mode=0o700)
            self._owner_only(private, directory=True)
            path = remote_hermes.connection_path(root)
            legacy = {
                "schema_version": 1,
                "mode": "remote",
                "label": "Legacy remote",
                "binding_id": "a" * 32,
                "endpoint": "https://hermes.example",
                "api_key": DISTINCTIVE_SECRET,
            }
            path.write_text(json.dumps(legacy), encoding="utf-8")
            self._owner_only(path, directory=False)
            reserve_mentat_server(root)
            try:
                public = remote_hermes.public_connection_payload(root)
                self.assertEqual(public["status"], "unavailable")
                self.assertEqual(
                    public["error_code"],
                    "connection_migration_server_running",
                )
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), legacy)
                self.assertFalse(remote_hermes.connection_credential_path(root).exists())
            finally:
                release_mentat_server(root)

    def test_local_connection_test_requires_a_verified_cli_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            with self.assertRaisesRegex(
                remote_hermes.RemoteHermesError,
                "local_connection_unavailable",
            ):
                remote_hermes.test_connection_mode(
                    root,
                    "local",
                    local_probe=lambda: (_ for _ in ()).throw(
                        remote_hermes.RemoteHermesError(
                            "local_connection_unavailable"
                        )
                    ),
                )
            result = remote_hermes.test_connection_mode(
                root,
                "local",
                local_probe=lambda: {
                    "trusted": True,
                    "platform": "hermes-agent",
                    "readiness": {"cli": "ok"},
                },
            )
            self.assertEqual(result["status"], "verified")
            self.assertEqual(result["discovery"]["readiness"], {"cli": "ok"})

    def test_public_connection_payload_uses_one_consistent_snapshot(self):
        state = remote_hermes.ConnectionState(
            "local",
            "Local Hermes",
            remote_hermes.RememberedRemote(
                "Remembered",
                "https://hermes.example",
                remote_hermes.CredentialSource(
                    "environment",
                    "MENTAT_REMOTE_HERMES_API_KEY",
                ),
            ),
            "a" * 32,
        )
        selection = remote_hermes.ConnectionSelection(
            "local",
            "Local Hermes",
            None,
            None,
            "a" * 32,
        )
        with patch.object(
            remote_hermes,
            "_load_state_and_selection",
            return_value=(state, selection),
        ) as snapshot:
            payload = remote_hermes.public_connection_payload(Path("/not-read"))
        snapshot.assert_called_once_with(Path("/not-read"))
        self.assertEqual(payload["selection"]["mode"], "local")
        self.assertEqual(payload["selection"]["binding_id"], "a" * 32)
        self.assertEqual(
            payload["selection"]["remembered_remote_label"],
            "Remembered",
        )

    def test_missing_active_environment_key_never_falls_back_to_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            with patch.dict(
                os.environ,
                {"MENTAT_REMOTE_HERMES_API_KEY": DISTINCTIVE_SECRET},
            ):
                source = remote_hermes.credential_source_from_values(
                    "environment",
                    name="MENTAT_REMOTE_HERMES_API_KEY",
                )
                preview = remote_hermes.preview_connection_from_source(
                    root,
                    label="Remote",
                    endpoint="https://hermes.example",
                    credential_source=source,
                )
                remote_hermes.confirm_connection_from_source(
                    root,
                    label="Remote",
                    endpoint="https://hermes.example",
                    credential_source=source,
                    confirmation_token=preview.confirmation_token,
                    client_factory=FakeDiscoveryClient,
                )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(
                    remote_hermes.RemoteHermesError,
                    "connection_credential_unavailable",
                ):
                    remote_hermes.load_connection(root)
                self.assertEqual(
                    json.loads(
                        remote_hermes.connection_path(root).read_text(
                            encoding="utf-8"
                        )
                    )["mode"],
                    "remote",
                )
                preview = remote_hermes.preview_remembered_connection(
                    root,
                    "local",
                )
                selected = remote_hermes.confirm_remembered_connection(
                    root,
                    "local",
                    preview.confirmation_token,
                    client_factory=FakeDiscoveryClient,
                )
                self.assertEqual(selected["selection"]["mode"], "local")
                self.assertIsNotNone(
                    remote_hermes.load_connection_state(root).remote,
                )

    def test_unchanged_selection_is_verified_without_rewriting_secret_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            payload = self._remote_payload()
            self._confirm(root, payload)
            path = remote_hermes.connection_path(root)
            before = (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
            preview = remote_hermes.preview_connection(root, payload)
            self.assertFalse(preview.changed)
            with patch.object(remote_hermes, "write_json_atomic", wraps=remote_hermes.write_json_atomic) as writer:
                result = remote_hermes.confirm_connection(
                    root,
                    payload,
                    preview.confirmation_token,
                    client_factory=FakeDiscoveryClient,
                )
            self.assertEqual(result["selection"]["binding_id"], remote_hermes.load_connection(root).binding_id)
            writer.assert_not_called()
            self.assertEqual((path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns), before)

    def test_unsafe_or_newer_private_records_fail_closed(self):
        cases = (
            "symlink",
            "hardlink",
            "broad",
            "oversize",
            "newer",
            "remote_default_binding",
            "local_extra_fields",
            "local_default_custom",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = self._root(temporary)
                private = root / "private"
                private.mkdir(mode=0o700)
                path = remote_hermes.connection_path(root)
                valid = {
                    "schema_version": 1,
                    "mode": "local",
                    "label": "Local Hermes",
                    "binding_id": "local-default",
                }
                if case == "symlink":
                    outside = Path(temporary) / "outside.json"
                    outside.write_text(json.dumps(valid), encoding="utf-8")
                    path.symlink_to(outside)
                elif case == "hardlink":
                    outside = Path(temporary) / "outside.json"
                    outside.write_text(json.dumps(valid), encoding="utf-8")
                    os.link(outside, path)
                elif case == "oversize":
                    path.write_bytes(b"{" + b" " * remote_hermes.MAX_CONNECTION_BYTES + b"}")
                else:
                    if case == "newer":
                        valid["schema_version"] = 2
                    elif case == "remote_default_binding":
                        valid.update(
                            mode="remote",
                            endpoint="https://hermes.example",
                            api_key=DISTINCTIVE_SECRET,
                        )
                    elif case == "local_extra_fields":
                        valid.update(endpoint=None, api_key=None)
                    elif case == "local_default_custom":
                        valid["label"] = "Custom local"
                    path.write_text(json.dumps(valid), encoding="utf-8")
                    path.chmod(0o644 if case == "broad" else 0o600)
                if case not in {"broad", "newer"} and path.exists() and not path.is_symlink():
                    path.chmod(0o600)
                with self.assertRaises(remote_hermes.RemoteHermesError):
                    remote_hermes.load_connection(root)

    def test_discovery_uses_fixed_paths_and_keeps_auth_off_public_health(self):
        queue = ResponseQueue(
            [
                FakeResponse(200, {"status": "ok", "api_key": DISTINCTIVE_SECRET}),
                FakeResponse(200, _health()),
                FakeResponse(200, _capabilities()),
            ]
        )
        client = remote_hermes.RemoteHermesClient(
            "https://hermes.example",
            DISTINCTIVE_SECRET,
            connection_factory=queue,
        )
        result = client.discover()
        self.assertEqual([call["path"] for call in queue.calls], ["/health", "/health/detailed", "/v1/capabilities"])
        self.assertNotIn("Authorization", queue.calls[0]["headers"])
        self.assertEqual(queue.calls[1]["headers"]["Authorization"], f"Bearer {DISTINCTIVE_SECRET}")
        self.assertEqual(queue.calls[2]["headers"]["Authorization"], f"Bearer {DISTINCTIVE_SECRET}")
        self.assertTrue(all(connection.closed for connection in queue.connections))
        serialized = json.dumps(result)
        self.assertNotIn(DISTINCTIVE_SECRET, serialized)
        self.assertEqual(result["readiness"], {"config": "ok", "gateway": "ok"})
        self.assertEqual(result["capabilities"], ["chat_completions", "run_submission"])
        self.assertNotIn("future_secret_feature", serialized)

    def test_connection_diagnostics_reports_local_healthy_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            result = remote_hermes.connection_diagnostics(
                root,
                client_factory=FakeDiscoveryClient,
            )
        self.assertEqual(result["mode"], "local")
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(FakeDiscoveryClient.calls, [])

    def test_connection_diagnostics_returns_only_bounded_remote_health(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            self._confirm(root)
            result = remote_hermes.connection_diagnostics(
                root,
                client_factory=DegradedDiscoveryClient,
            )
        self.assertEqual(result["mode"], "remote")
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["category"], "degraded")
        self.assertEqual(result["model"], "anthropic/claude-test")
        serialized = json.dumps(result)
        self.assertNotIn(DISTINCTIVE_SECRET, serialized)
        self.assertNotIn("hermes.example", serialized)
        self.assertNotIn("binding_id", serialized)

    def test_connection_diagnostics_classifies_remote_failures_without_details(self):
        class FailingClient(FakeDiscoveryClient):
            failure_code = "remote_unavailable"

            def discover(self):
                raise remote_hermes.RemoteHermesError(self.failure_code)

        cases = {
            "remote_authentication_failed": "unauthenticated",
            "remote_certificate_invalid": "unreachable",
            "remote_timeout": "unreachable",
            "remote_schema_unsupported": "unsupported",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            self._confirm(root)
            for code, category in cases.items():
                with self.subTest(code=code):
                    FailingClient.failure_code = code
                    result = remote_hermes.connection_diagnostics(
                        root,
                        client_factory=FailingClient,
                    )
                    self.assertEqual(result["status"], "error")
                    self.assertEqual(result["category"], category)
                    serialized = json.dumps(result)
                    self.assertNotIn(code, serialized)
                    self.assertNotIn(DISTINCTIVE_SECRET, serialized)
                    self.assertNotIn("hermes.example", serialized)

    def test_short_single_label_origins_do_not_false_positive_as_reflections(self):
        for endpoint in ("https://a", "https://ok"):
            with self.subTest(endpoint=endpoint):
                queue = ResponseQueue(
                    [
                        FakeResponse(200, {"status": "ok"}),
                        FakeResponse(200, _health()),
                        FakeResponse(200, _capabilities()),
                    ]
                )
                result = remote_hermes.RemoteHermesClient(
                    endpoint,
                    DISTINCTIVE_SECRET,
                    connection_factory=queue,
                ).discover()
                self.assertEqual(result["status"], "healthy")

    def test_default_https_connection_requires_certificate_and_hostname_verification(self):
        captured = {}

        class CapturingConnection:
            def __init__(self, host, *, port, timeout, context):
                captured.update(host=host, port=port, timeout=timeout, context=context)

        with patch.object(remote_hermes.http.client, "HTTPSConnection", CapturingConnection):
            client = remote_hermes.RemoteHermesClient("https://hermes.example", DISTINCTIVE_SECRET)
            client._connection()
        self.assertEqual(captured["host"], "hermes.example")
        self.assertTrue(captured["context"].check_hostname)
        self.assertEqual(captured["context"].verify_mode, ssl.CERT_REQUIRED)

    def test_redirect_auth_schema_and_response_limits_fail_with_bounded_codes(self):
        cases = (
            (FakeResponse(302, {}, {"Location": "https://evil.example"}), "remote_redirect_refused"),
            (FakeResponse(401, {}), "remote_authentication_failed"),
            (FakeResponse(200, {}, {"Content-Type": "text/html"}), "remote_content_type_invalid"),
            (FakeResponse(200, b"{" + b"x" * 4096, {"Content-Length": "4097"}), "remote_response_too_large"),
            (FakeResponse(200, b'{"status": NaN}'), "remote_response_invalid"),
            (FakeResponse(200, b'{"status": 1e400}'), "remote_response_invalid"),
        )
        for response, code in cases:
            with self.subTest(code=code):
                queue = ResponseQueue([response])
                client = remote_hermes.RemoteHermesClient(
                    "https://hermes.example",
                    DISTINCTIVE_SECRET,
                    maximum_bytes=4096,
                    connection_factory=queue,
                )
                with self.assertRaisesRegex(remote_hermes.RemoteHermesError, code):
                    client._request_json("/health/detailed", authenticated=True)
        client = remote_hermes.RemoteHermesClient("https://hermes.example", DISTINCTIVE_SECRET)
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_path_not_allowed"):
            client._request_json("/arbitrary", authenticated=True)

    def test_public_partial_commit_failure_is_explicit_and_secret_free(self):
        payload, status = remote_hermes.public_error(
            remote_hermes.RemoteHermesError("connection_commit_partial")
        )
        self.assertEqual(status, 500)
        self.assertTrue(payload["partial"])
        self.assertNotIn(DISTINCTIVE_SECRET, json.dumps(payload))

    def test_authenticated_schema_mismatch_or_disabled_auth_fails_closed(self):
        bad_health = _health()
        bad_health["platform"] = "lookalike"
        mismatched_health = _health()
        mismatched_health["readiness"]["status"] = "degraded"
        inconsistent_checks = _health()
        inconsistent_checks["readiness"]["checks"]["gateway"]["status"] = "degraded"
        degraded_without_check = _health(status="degraded")
        for item in degraded_without_check["readiness"]["checks"].values():
            item["status"] = "ok"
        empty_checks = _health()
        empty_checks["readiness"]["checks"] = {}
        wrong_status_type = _health()
        wrong_status_type["status"] = []
        wrong_status_type["readiness"]["status"] = []
        cases = (
            [FakeResponse(200, {"status": "ok"}), FakeResponse(200, bad_health)],
            [FakeResponse(200, {"status": "ok"}), FakeResponse(200, mismatched_health)],
            [FakeResponse(200, {"status": "ok"}), FakeResponse(200, inconsistent_checks)],
            [FakeResponse(200, {"status": "ok"}), FakeResponse(200, degraded_without_check)],
            [FakeResponse(200, {"status": "ok"}), FakeResponse(200, empty_checks)],
            [FakeResponse(200, {"status": "ok"}), FakeResponse(200, wrong_status_type)],
            [FakeResponse(200, {"status": "ok"}), FakeResponse(200, _health()), FakeResponse(200, _capabilities(auth_required=False))],
            [FakeResponse(200, {"status": "ok"}), FakeResponse(200, _health()), FakeResponse(200, _capabilities(model="../../secret"))],
        )
        for responses in cases:
            with self.subTest():
                client = remote_hermes.RemoteHermesClient(
                    "https://hermes.example",
                    DISTINCTIVE_SECRET,
                    connection_factory=ResponseQueue(responses),
                )
                with self.assertRaises(remote_hermes.RemoteHermesError):
                    client.discover()

    def test_authenticated_metadata_cannot_reflect_bearer_key(self):
        reflected_key = "reflected_secret_12345"
        reflected_health = _health()
        reflected_capabilities = _capabilities()
        cases = []

        reflected_health["version"] = reflected_key
        cases.append((reflected_health, _capabilities()))

        reflected_health = _health()
        reflected_capabilities["model"] = reflected_key
        cases.append((reflected_health, reflected_capabilities))

        reflected_health = _health()
        reflected_health["readiness"]["checks"] = {
            reflected_key: {"status": "ok"}
        }
        cases.append((reflected_health, _capabilities()))

        for health, capabilities in cases:
            with self.subTest():
                client = remote_hermes.RemoteHermesClient(
                    "https://hermes.example",
                    reflected_key,
                    connection_factory=ResponseQueue(
                        [
                            FakeResponse(200, {"status": "ok"}),
                            FakeResponse(200, health),
                            FakeResponse(200, capabilities),
                        ]
                    ),
                )
                with self.assertRaisesRegex(
                    remote_hermes.RemoteHermesError,
                    "remote_private_reflection",
                ) as captured:
                    client.discover()
                public, status = remote_hermes.public_error(captured.exception)
                self.assertEqual(status, 502)
                self.assertNotIn(reflected_key, json.dumps(public))

    def test_authenticated_metadata_cannot_reflect_private_endpoint(self):
        cases = []

        reflected_health = _health(version="private-hermes.example")
        cases.append(
            (
                "https://private-hermes.example",
                reflected_health,
                _capabilities(),
            )
        )

        reflected_capabilities = _capabilities(model="private-hermes.example")
        cases.append(
            (
                "https://private-hermes.example",
                _health(),
                reflected_capabilities,
            )
        )

        cases.append(
            (
                "http://127.0.0.1:8642",
                _health(),
                _capabilities(model="127.0.0.1"),
            )
        )

        for endpoint, health, capabilities in cases:
            with self.subTest(endpoint=endpoint):
                client = remote_hermes.RemoteHermesClient(
                    endpoint,
                    DISTINCTIVE_SECRET,
                    connection_factory=ResponseQueue(
                        [
                            FakeResponse(200, {"status": "ok"}),
                            FakeResponse(200, health),
                            FakeResponse(200, capabilities),
                        ]
                    ),
                )
                with self.assertRaisesRegex(
                    remote_hermes.RemoteHermesError,
                    "remote_private_reflection",
                ):
                    client.discover()

    def test_certificate_exception_is_reduced_to_safe_error_code(self):
        class CertificateFailure:
            def request(self, *_args, **_kwargs):
                raise ssl.SSLCertVerificationError("certificate mentions " + DISTINCTIVE_SECRET)

            def close(self):
                pass

        client = remote_hermes.RemoteHermesClient(
            "https://hermes.example",
            DISTINCTIVE_SECRET,
            connection_factory=lambda *_args: CertificateFailure(),
        )
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_certificate_invalid") as captured:
            client._request_json("/health/detailed", authenticated=True)
        payload, status = remote_hermes.public_error(captured.exception)
        self.assertEqual(status, 502)
        self.assertNotIn(DISTINCTIVE_SECRET, json.dumps(payload))

    def test_server_routes_never_echo_credential_or_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            self._confirm(root)
            payload = {"mode": "local"}
            with patch.object(server, "DATA_DIR", root):
                preview, preview_status = server.preview_hermes_connection(payload)
                self.assertEqual(preview_status, 200)
                serialized = json.dumps(preview)
                self.assertNotIn(DISTINCTIVE_SECRET, serialized)
                self.assertNotIn("hermes.example", serialized)
                confirmation = {**payload, "confirmation_token": preview["confirmation_token"]}
                with patch.object(
                    server,
                    "confirm_remote_hermes_connection",
                    return_value={
                        "status": "selected",
                        "selection": {"mode": "remote", "label": "Workshop Hermes", "binding_id": "b" * 32, "configured": True},
                        "discovery": {"trusted": True, "status": "healthy"},
                    },
                ) as confirm:
                    result, result_status = server.select_hermes_connection(confirmation)
                self.assertEqual(result_status, 200)
                self.assertNotIn(DISTINCTIVE_SECRET, json.dumps(result))
                confirm.assert_called_once()
                self.assertEqual(confirm.call_args.args[1], "local")
                rejected, rejected_status = server.preview_hermes_connection(
                    {
                        "mode": "remote",
                        "api_key": DISTINCTIVE_SECRET,
                    }
                )
                self.assertEqual(rejected_status, 400)
                self.assertNotIn(DISTINCTIVE_SECRET, json.dumps(rejected))
            self.assertIn("/api/hermes/connection", server.API_ROUTES)
            route_patterns = [pattern.pattern for pattern, _handler, _payload in server.POST_ROUTES]
            self.assertIn(r"^/api/hermes/connection/preview$", route_patterns)
            self.assertIn(r"^/api/hermes/connection$", route_patterns)
            self.assertIn(r"^/api/hermes/connection/test$", route_patterns)

    def test_connection_record_remains_excluded_from_general_backup_contract(self):
        source = Path(remote_hermes.__file__).resolve().parents[0] / "data_backup_restore.py"
        backup_source = source.read_text(encoding="utf-8")
        self.assertIn('"credentials", "classification": "excluded_secrets"', backup_source)
        self.assertNotIn(remote_hermes.CONNECTION_FILE_NAME, backup_source)

    def test_real_general_backup_excludes_connection_record_endpoint_and_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._root(temporary)
            base = Path(temporary)
            config = runtime_config.AppConfig(
                config_files=(),
                host="127.0.0.1",
                port=8888,
                data_dir=root,
                public_dir=base / "public",
                hermes_home=base / "hermes",
                obsidian_vault=base / "vault",
                data_dir_source="cli",
            )
            self.assertIsNone(runtime_config.prepare_data_root_for_startup(config))
            self._confirm(root)
            result = create_durable_backup(root)
            self.assertEqual(result.status, "created")
            archive = root / "backups" / result.backup_name
            self.assertNotIn(DISTINCTIVE_SECRET.encode("utf-8"), archive.read_bytes())
            self.assertNotIn(b"hermes.example", archive.read_bytes())
            with zipfile.ZipFile(archive) as opened:
                self.assertNotIn(remote_hermes.CONNECTION_FILE_NAME, opened.namelist())
                archived_bytes = b"\n".join(
                    opened.read(name)
                    for name in opened.namelist()
                    if not name.endswith("/")
                )
            self.assertNotIn(DISTINCTIVE_SECRET.encode("utf-8"), archived_bytes)
            self.assertNotIn(b"hermes.example", archived_bytes)


if __name__ == "__main__":
    unittest.main()
