from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
import base64
import io
from pathlib import Path
import socket
import threading
import time
import unittest
from unittest.mock import patch

import mentat_db
import project_inference_broker as broker
import project_worker_journal as journal
from private_state import private_state_lock
from tests import test_project_worker_journal as fixtures
from tests import test_task_inputs as task_fixture
from agent_registry import AgentRegistry
from tests import test_project_context as context_fixture
from mentat import project_worker_namespace as namespaces
from mentat import project_worker_scope as scopes


class ProjectInferenceBrokerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProjectWorkerJournalTests()
        class HermesFixtureRegistry:
            def __init__(self, root, **_):
                self.registry = AgentRegistry(root, supported_runtime_types=("hermes",))
            def create_agent(self, **kwargs):
                kwargs["runtime_type"] = "hermes"
                return self.registry.create_agent(**kwargs)
        with patch.object(task_fixture, "AgentRegistry", HermesFixtureRegistry):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.run = self.fixture._prepare()
        self.inputs = broker.derive_qualification_inputs(self.root, self.run, fixtures.GENERATION)
        self.backend = broker.SyntheticCompletionBackend()
        self.scope = broker.SyntheticScope(wall_seconds=20)
        self.broker = broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION,
                                                        self.backend, self.scope)

    def _body(self, **extra):
        body = {"model": fixtures.SNAPSHOT["model"], "stream": True, "tools": [],
                "messages": [{"role": "system", "content": "worker system is untrusted and discarded"},
                             {"role": "user", "content": self.inputs.query.decode("utf-8")}]}
        body.update(extra)
        return json.dumps(body).encode()

    def _call_state(self):
        with closing(mentat_db.connect(self.root)) as connection:
            return connection.execute("SELECT state,work_debit,response_text,request_digest FROM mentat_project_worker_calls").fetchone()

    def _prepare_image_fixture(self):
        from PIL import Image
        from agent_console_attachments import create_attachment
        output = io.BytesIO()
        Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
        image = output.getvalue()
        def upload(instance, *_):
            return create_attachment(instance.root, original_name="floorplan.png", content=image)["id"]
        self.fixture.doCleanups()
        with patch.object(context_fixture.ProjectContextTests, "upload", upload), patch.dict(fixtures.SNAPSHOT, {"supports_vision": True}):
            self.setUp()

    def test_prepared_query_uses_exact_context_instructions_and_selected_bytes(self):
        prepared = json.loads(self.inputs.query)
        self.assertEqual(prepared["format"], 1)
        self.assertEqual(prepared["operation"], "project_proposal")
        self.assertEqual(prepared["instructions"], "Plan the garage using supplied dimensions.")
        self.assertEqual(len(prepared["files"]), 1)
        self.assertEqual(prepared["files"][0]["ordinal"], 0)
        self.assertNotIn("query", repr(self.inputs))
        self.assertNotIn(prepared["instructions"], repr(self.inputs))

    def test_one_call_constructs_host_request_and_duplicate_uses_durable_cache(self):
        body = self._body(temperature=1.7, max_tokens=100, stream_options={"include_usage": True})
        first = self.broker.handle_body(body)
        self.assertEqual(first, {"state": "succeeded", "text": "PROBE_OK"})
        self.assertEqual(self.broker.handle_body(body), first)
        self.assertEqual(self.backend.calls, 1)
        actual = self.backend.requests[0]
        self.assertEqual(set(actual), {"model", "messages", "stream", "max_tokens"})
        self.assertEqual(actual["max_tokens"], fixtures.POLICY["max_output_tokens"])
        self.assertFalse(actual["stream"])
        self.assertEqual(actual["messages"][0]["content"], broker.SYSTEM)
        self.assertEqual(actual["messages"][1]["content"], self.inputs.query.decode())
        self.assertEqual(tuple(self._call_state()[:3]), ("succeeded", 1, "PROBE_OK"))

    def test_changed_body_after_one_call_never_invokes_backend_again(self):
        self.broker.handle_body(self._body())
        self.assertEqual(self.broker.handle_body(self._body(temperature=.1)), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 1)

    def test_missing_changed_or_unprepared_content_spends_no_call(self):
        cases = [self._body(model="other"), self._body(stream=False), self._body(tools=[{"type": "function"}]),
                 self._body(base_url="https://invalid.test"), self._body(max_tokens=9000),
                 self._body(messages=[{"role": "user", "content": "different input"}]),
                 self._body(messages=[{"role": "user", "content": {"input_image": "hidden"}}]),
                 b'{"model":"mentat-probe","model":"other","messages":[],"stream":true}']
        for raw in cases:
            with self.subTest(raw=raw[:50]):
                self.broker = broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION,
                                                                 self.backend, self.scope)
                self.assertEqual(self.broker.handle_body(raw), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 0)
        self.assertIsNone(self._call_state())

    def test_missing_or_substituted_selected_blob_rejects_whole_input_set(self):
        from agent_console_attachments import read_attachment_bytes
        metadata, payload = read_attachment_bytes(self.root, self.fixture.fixture.fixture.fixture.attachment)
        with patch.object(broker, "read_attachment_bytes", return_value=(metadata, payload + b"changed")):
            self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 0)
        self.assertIsNone(self._call_state())

    def test_existing_reserved_after_crash_does_not_reacquire_submission_token(self):
        _, digest = broker._host_request(self._body(), self.inputs, fixtures.POLICY, fixtures.SNAPSHOT)
        with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            journal.reserve_call(connection, run_id=self.run, generation=fixtures.GENERATION, request_digest=digest)
            connection.commit()
        self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 0)
        self.assertEqual(tuple(self._call_state()[:2]), ("reserved", 1))

    def test_crash_after_unknown_commit_before_start_stays_spent_and_unretried(self):
        with patch.object(self.backend, "_start", side_effect=OSError("controlled crash after commit")):
            self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        reopened = broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION,
                                                      self.backend, self.scope)
        self.assertEqual(reopened.handle_body(self._body()), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 0)
        self.assertEqual(tuple(self._call_state()[:2]), ("unknown", 1))

    def test_unknown_and_invalid_response_are_not_automatically_retried(self):
        self.backend._unknown = True
        self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 1)
        self.assertEqual(tuple(self._call_state()[:2]), ("unknown", 1))

    def test_oversized_result_is_retained_as_fixed_failure_without_text(self):
        self.backend._text = "x" * (32768 + 1)
        expected = {"state": "failed", "disposition": "oversized"}
        self.assertEqual(self.broker.handle_body(self._body()), expected)
        self.assertEqual(self.broker.handle_body(self._body()), expected)
        self.assertEqual(tuple(self._call_state()[:3]), ("failed", 1, None))
        self.assertEqual(self.backend.calls, 1)

    def test_concurrent_first_requests_start_only_one_synthetic_call(self):
        release = threading.Event()
        self.backend._release = release
        outcomes = []
        thread = threading.Thread(target=lambda: outcomes.append(self.broker.handle_body(self._body())))
        thread.start()
        try:
            self.assertTrue(self.backend.started.wait(10))
            self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
            self.assertEqual(self.backend.calls, 1)
        finally:
            release.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, [{"state": "succeeded", "text": "PROBE_OK"}])

    def test_stop_does_not_wait_on_backend_and_late_result_is_history_only(self):
        release = threading.Event()
        self.backend._release = release
        outcomes = []
        thread = threading.Thread(target=lambda: outcomes.append(self.broker.handle_body(self._body())))
        thread.start()
        try:
            self.assertTrue(self.backend.started.wait(10))
            started = time.monotonic()
            self.broker.stop()
            self.assertLess(time.monotonic() - started, .5)
            self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        finally:
            release.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, [broker._UNKNOWN])
        self.assertEqual(tuple(self._call_state()[:3]), ("succeeded", 1, "PROBE_OK"))
        self.assertEqual(self.backend.calls, 1)

    def test_restore_epoch_fences_known_result_replay(self):
        self.broker.handle_body(self._body())
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("UPDATE mentat_project_context_access_state SET approval_epoch=randomblob(32)")
            connection.commit()
        self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 1)

    def test_scope_exit_and_expired_clock_refuse_new_reservation(self):
        self.scope.alive = False
        self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        self.scope.alive = True
        self.scope.deadline = time.monotonic() - 1
        self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 0)
        self.assertIsNone(self._call_state())

    def test_arbitrary_backend_or_scope_callback_is_not_a_qualification_factory(self):
        for backend, scope in ((lambda *_: "answer", self.scope), (self.backend, lambda: True)):
            with self.assertRaises(broker.InferenceBrokerError):
                broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION, backend, scope)

    def test_native_input_derivation_and_request_use_exact_accepted_image_bytes(self):
        self._prepare_image_fixture()
        inputs = self.inputs
        self.assertEqual(inputs.image_mime, "image/png")
        self.assertEqual(hashlib.sha256(inputs.image).hexdigest(), inputs.image_digest)
        annotated = inputs.query.decode() + "\n\n[Image attached at: /inputs/image" + inputs.image_extension + "]"
        user = [{"type": "text", "text": annotated}, {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(inputs.image).decode()}}]
        body = self._body(messages=[{"role": "user", "content": user}])
        self.assertEqual(self.broker.handle_body(body), {"state": "succeeded", "text": "PROBE_OK"})
        accepted = self.backend.requests[0]["messages"][1]["content"][1]["image_url"]["url"]
        self.assertEqual(base64.b64decode(accepted.split(",", 1)[1], validate=True), inputs.image)
        self.assertEqual(self.backend.calls, 1)

    def test_submission_has_committed_unknown_and_private_lock_is_not_held_during_wait(self):
        original_start = self.backend._start
        def start(request, deadline):
            self.assertEqual(self._call_state()[0], "unknown")
            return original_start(request, deadline)
        release = threading.Event()
        self.backend._release = release
        outcomes = []
        with patch.object(self.backend, "_start", side_effect=start):
            thread = threading.Thread(target=lambda: outcomes.append(self.broker.handle_body(self._body())))
            thread.start()
            try:
                self.assertTrue(self.backend.started.wait(10))
                # A real guarded owner write can finish while response is pending.
                with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute("UPDATE mentat_project_context_access_state SET approval_epoch=randomblob(32)")
                    connection.commit()
            finally:
                release.set()
                thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, [broker._UNKNOWN])
        self.assertEqual(self._call_state()[0], "succeeded")  # Late historical truth only.

    def test_commit_failures_before_or_after_each_publish_never_start_twice(self):
        original_connect = mentat_db.connect
        for target, after in ((1, False), (1, True), (2, False), (2, True), (3, False), (3, True)):
            # Independent canonical fixture per fault: no state deletion/refund.
            if target != 1 or after:
                self.fixture.doCleanups()
                self.setUp()
            counter = {"commit": 0}
            class ConnectionProxy:
                def __init__(self, connection):
                    object.__setattr__(self, "wrapped", connection)
                def __getattr__(self, name):
                    return getattr(self.wrapped, name)
                def __setattr__(self, name, value):
                    setattr(self.wrapped, name, value)
                def commit(self):
                    counter["commit"] += 1
                    if counter["commit"] == target and not after:
                        raise OSError("controlled commit refusal")
                    self.wrapped.commit()
                    if counter["commit"] == target and after:
                        raise OSError("controlled lost commit response")
            with self.subTest(target=target, after=after), patch.object(mentat_db, "connect",
                    side_effect=lambda root: ConnectionProxy(original_connect(root))):
                self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
            self.assertLessEqual(self.backend.calls, 1)
            prior = self.backend.calls
            self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
            self.assertEqual(self.backend.calls, prior)

    @unittest.skipUnless(scopes.IS_LINUX, "Actual Linux namespace qualification")
    def test_stock_namespace_connects_to_durable_broker_and_exact_input_query(self):
        values = [os.environ.get(key) for key in ("MENTAT_TEST_HERMES_SOURCE", "MENTAT_TEST_HERMES_VENV", "MENTAT_TEST_PYTHON_ROOT")]
        if not all(values):
            self.skipTest("Pinned official stock installation not supplied")
        self._prepare_image_fixture()
        roots = namespaces.RuntimeRoots(*(Path(value) for value in values))
        scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=20))
        prepared = namespaces.PreparedNamespace(roots, self.inputs.query, hashlib.sha256(self.inputs.query).hexdigest(),
                                               fixtures.SNAPSHOT["model"], vision=True, image=self.inputs.image,
                                               image_digest=self.inputs.image_digest, image_extension=self.inputs.image_extension)
        host, worker = socket.socketpair()
        thread = None
        actual_broker = None
        scope_receipt = None
        try:
            from tests.qualification_scope_support import start_recorded_scope, close_recorded_scope
            scope_receipt = start_recorded_scope(self.root, self.run, fixtures.GENERATION, scope)
            actual_broker = broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION,
                                                               self.backend, scope)
            thread = threading.Thread(target=actual_broker.serve, args=(host,))
            thread.start()
            handle = scope.handoff_namespace(prepared, worker)
            from copy import copy
            with self.assertRaises(scopes.WorkerScopeError): copy(handle).wait()
            result = handle.wait()
            self.assertEqual(result["text"], "PROBE_OK")
            with self.assertRaises(scopes.WorkerScopeError):
                handle.completion_witness()
            result['text'] = 'caller-edited text is not the native result'
            scope.close_verified()
            from mentat.project_namespace_evidence import completion_metadata
            cloned_handle = copy(handle)
            cloned_handle._verified_result = ('cloned issuer text', 1)
            with self.assertRaises(scopes.WorkerScopeError): cloned_handle.completion_witness()
            witness = handle.completion_witness()
            private = completion_metadata(witness)
            self.assertEqual(private['result']['text'], 'PROBE_OK')
            self.assertEqual(private['query_digest'], hashlib.sha256(self.inputs.query).hexdigest())
            self.assertEqual(private['image_digest'], self.inputs.image_digest)
            self.assertIsNone(private['runtime_image_digest'])
            self.assertFalse(private['sealed_libraries'])
            private['result']['text'] = 'changed metadata copy'
            self.assertEqual(completion_metadata(witness)['result']['text'], 'PROBE_OK')
            self.assertIs(handle.completion_witness(), witness)
            with self.assertRaises(scopes.WorkerScopeError): copy(handle).completion_witness()
            with self.assertRaises(ValueError): completion_metadata(copy(witness))
            self.assertEqual(self.backend.calls, 1)
            content = self.backend.requests[0]["messages"][1]["content"]
            self.assertEqual(content[0]["text"], self.inputs.query.decode())
            self.assertEqual(base64.b64decode(content[1]["image_url"]["url"].split(",", 1)[1], validate=True), self.inputs.image)
            self.assertEqual(tuple(self._call_state()[:3]), ("succeeded", 1, "PROBE_OK"))
        finally:
            if actual_broker is not None:
                actual_broker.stop()
            if not scope._closed:
                scope.close_verified()
            if scope_receipt is not None:
                close_recorded_scope(self.root, self.run, fixtures.GENERATION, scope, scope_receipt)
            for endpoint in (host, worker):
                try:
                    endpoint.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                endpoint.close()
            if thread is not None:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            prepared.close()

    def test_scope_wall_and_smaller_resource_policy_fail_before_debit(self):
        with self.assertRaises(broker.InferenceBrokerError):
            broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION,
                                                self.backend, broker.SyntheticScope(wall_seconds=30))
        for field, value in (("memory_bytes", 128 * 1024 * 1024), ("processes", 8), ("cpu_percent", 50)):
            with self.subTest(field=field), patch.object(self.broker, "_policy_limits",
                    scopes.WorkerScopeLimits(**{field: value})):
                self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
            self.assertEqual(self.backend.calls, 0)
            self.assertIsNone(self._call_state())
            self.broker = broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION,
                                                             self.backend, self.scope)

    def test_mutated_scope_deadline_cannot_refresh_original_wall(self):
        original = self.broker.deadline
        self.scope.deadline += 3600
        self.assertEqual(self.broker.deadline, original)

    def test_missing_nonfinite_expired_or_unstarted_scope_is_refused_before_transport(self):
        for deadline in (None, float("nan"), float("inf"), time.monotonic() - 1):
            scope = broker.SyntheticScope()
            scope.deadline = deadline
            with self.subTest(deadline=deadline), self.assertRaises(broker.InferenceBrokerError):
                broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION, self.backend, scope)
        self.assertEqual(self.backend.calls, 0)
        self.assertIsNone(self._call_state())

    def test_known_nontext_response_is_distinct_from_unresolved_outcome(self):
        self.backend._text = None
        self.assertEqual(self.broker.handle_body(self._body()), {"state": "failed", "disposition": "non_text"})
        self.assertEqual(self._call_state()[0], "failed")
        self.assertEqual(self.backend.calls, 1)

    def test_lost_or_nonfinite_live_scope_deadline_fences_before_debit(self):
        original = self.scope.deadline
        for value in (None, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.scope.deadline = value
                self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
                self.assertEqual(self.backend.calls, 0)
                self.assertIsNone(self._call_state())
                self.scope.deadline = original
                self.broker = broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION,
                                                                 self.backend, self.scope)

    def test_missing_or_malformed_run_authority_receipt_refuses_constructor_and_work(self):
        with closing(mentat_db.connect(self.root)) as connection:
            original = dict(connection.execute("SELECT * FROM mentat_run_store_state").fetchone())
            connection.execute("DELETE FROM mentat_run_store_state")
            connection.commit()
        with self.assertRaises(RuntimeError):
            broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION, self.backend, self.scope)
        self.assertEqual(self.broker.handle_body(self._body()), broker._UNKNOWN)
        self.assertEqual(self.backend.calls, 0)
        self.assertIsNone(self._call_state())
        with closing(mentat_db.connect(self.root)) as connection:
            columns = list(original)
            connection.execute("INSERT INTO mentat_run_store_state(" + ",".join(columns) + ") VALUES(" +
                               ",".join("?" for _ in columns) + ")", [original[key] for key in columns])
            connection.execute("UPDATE mentat_run_store_state SET source_sha256=?", ("z" * 64,))
            connection.commit()
        with self.assertRaises(RuntimeError):
            broker.QualificationInferenceBroker(self.root, self.run, fixtures.GENERATION, self.backend, self.scope)
        self.assertEqual(self.backend.calls, 0)

    def test_private_backup_accepts_only_claimed_dormant_journal_after_completion(self):
        import private_console_unit
        self.broker.handle_body(self._body())
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        self.assertEqual(tuple(self._call_state()[:3]), ("succeeded", 1, "PROBE_OK"))


if __name__ == "__main__":
    unittest.main()
