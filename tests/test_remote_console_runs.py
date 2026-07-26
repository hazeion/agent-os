from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import agent_run_history
from hermes_transport import (
    RemoteHermesConsoleTransport,
    TransportBinding,
)
import remote_hermes
import server


SECRET = "remote-console-secret-NEVER-RETURN"
ENDPOINT = "https://remote-console.example"
REMOTE_RUN_ID = "run_" + ("a" * 32)


def health_payload():
    return {
        "status": "ok",
        "platform": "hermes-agent",
        "version": "0.18.2",
        "readiness": {
            "status": "ok",
            "checks": {"config": {"status": "ok"}},
        },
    }


def capability_payload(**feature_updates):
    features = {
        "run_submission": True,
        "run_status": True,
        "run_events_sse": True,
        "run_stop": True,
    }
    features.update(feature_updates)
    return {
        "object": "hermes.api_server.capabilities",
        "platform": "hermes-agent",
        "model": "anthropic/claude-test",
        "auth": {"type": "bearer", "required": True},
        "runtime": {
            "mode": "server_agent",
            "tool_execution": "server",
            "split_runtime": False,
        },
        "features": features,
        "endpoints": {
            "health": {"method": "GET", "path": "/health"},
            "health_detailed": {"method": "GET", "path": "/health/detailed"},
            "runs": {"method": "POST", "path": "/v1/runs"},
            "run_status": {"method": "GET", "path": "/v1/runs/{run_id}"},
            "run_events": {"method": "GET", "path": "/v1/runs/{run_id}/events"},
            "run_stop": {"method": "POST", "path": "/v1/runs/{run_id}/stop"},
        },
    }


class FakeResponse:
    def __init__(self, status, payload=b"", *, content_type="application/json", headers=None):
        self.status = status
        self.raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.offset = 0
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(self.raw)),
        }
        self.headers.update(headers or {})

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, amount):
        return self.raw[:amount]

    def readline(self, amount):
        if self.offset >= len(self.raw):
            return b""
        end = self.raw.find(b"\n", self.offset)
        end = len(self.raw) if end < 0 else end + 1
        end = min(end, self.offset + amount)
        result = self.raw[self.offset:end]
        self.offset = end
        return result


class FakeConnection:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": dict(headers or {}),
            }
        )

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class ResponseQueue:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.connections = []
        self.timeouts = []

    def __call__(self, _scheme, _host, _port, timeout):
        self.timeouts.append(timeout)
        connection = FakeConnection(self.responses.pop(0), self.calls)
        self.connections.append(connection)
        return connection


class FakeRunClient:
    def __init__(self, *, events=(), statuses=(), capabilities=None):
        self.events = list(events)
        self.statuses = list(statuses)
        self.capabilities = capabilities or {
            "model": "anthropic/claude-test",
            "capabilities": [
                "run_submission",
                "run_status",
                "run_events_sse",
                "run_stop",
            ],
        }
        self.submitted = []
        self.stopped = []
        self.approvals = []
        self.clarifications = []
        self.iter_calls = 0
        self.last_event_ids = []

    def require_console_run_capabilities(self):
        if isinstance(self.capabilities, Exception):
            raise self.capabilities
        return self.capabilities

    def submit_run(self, prompt):
        self.submitted.append(prompt)
        return {"run_id": REMOTE_RUN_ID, "status": "started"}

    def iter_run_events(self, run_id, *, should_stop=None, last_event_id=None):
        self.assert_run_id(run_id)
        self.iter_calls += 1
        self.last_event_ids.append(last_event_id)
        for event in self.events:
            if should_stop is not None and should_stop():
                break
            if isinstance(event, Exception):
                raise event
            yield event

    def get_run(self, run_id):
        self.assert_run_id(run_id)
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status
        return status

    def stop_run(self, run_id):
        self.assert_run_id(run_id)
        self.stopped.append(run_id)
        return {"status": "stopping"}

    def respond_to_approval(self, run_id, request_id, choice):
        self.assert_run_id(run_id)
        self.approvals.append((request_id, choice))
        return {"request_id": request_id, "choice": choice, "resolved": 1}

    def respond_to_clarification(self, run_id, request_id, response):
        self.assert_run_id(run_id)
        self.clarifications.append((request_id, dict(response)))
        return {"request_id": request_id, "type": response["type"]}

    def read_profiles(self):
        return [
            {"id": "default", "is_default": True, "is_active": True, "served": True},
            {"id": "researcher", "is_default": False, "is_active": False, "served": True},
        ]

    def read_profile_runtimes(self):
        return {
            "default": {"provider": "openai-codex", "model": "gpt-5.6"},
            "researcher": {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
        }

    @staticmethod
    def assert_run_id(run_id):
        if run_id != REMOTE_RUN_ID:
            raise AssertionError("wrong upstream run")


class RemoteConsoleRunTests(unittest.TestCase):
    def setUp(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()
        server.AGENT_CONSOLE_REMOTE_WORKERS.clear()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()
        server.AGENT_CONSOLE_REMOTE_WORKERS.clear()

    def adapter(self, client=None, *, binding_id="b" * 32):
        return RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", binding_id),
            client=client or FakeRunClient(),
        )

    def test_capability_discovery_requires_exact_run_endpoint_templates(self):
        for mutation in ("missing_feature", "wrong_method", "wrong_path"):
            with self.subTest(mutation=mutation):
                capabilities = capability_payload()
                if mutation == "missing_feature":
                    capabilities["features"]["run_stop"] = False
                elif mutation == "wrong_method":
                    capabilities["endpoints"]["run_events"]["method"] = "POST"
                else:
                    capabilities["endpoints"]["run_status"]["path"] = "/arbitrary"
                queue = ResponseQueue(
                    [
                        FakeResponse(200, {"status": "ok"}),
                        FakeResponse(200, health_payload()),
                        FakeResponse(200, capabilities),
                    ]
                )
                client = remote_hermes.RemoteHermesClient(
                    ENDPOINT,
                    SECRET,
                    connection_factory=queue,
                )
                with self.assertRaises(remote_hermes.RemoteHermesError):
                    client.require_console_run_capabilities()

        queue = ResponseQueue(
            [
                FakeResponse(200, {"status": "ok"}),
                FakeResponse(200, health_payload()),
                FakeResponse(200, capability_payload()),
            ]
        )
        discovery = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=queue,
        ).require_console_run_capabilities()
        self.assertEqual(discovery["model"], "anthropic/claude-test")

    def test_fixed_run_json_operations_are_authenticated_and_schema_bound(self):
        queue = ResponseQueue(
            [
                FakeResponse(202, {"run_id": REMOTE_RUN_ID, "status": "started"}),
                FakeResponse(
                    200,
                    {
                        "object": "hermes.run",
                        "run_id": REMOTE_RUN_ID,
                        "session_id": "session_" + ("d" * 32),
                        "status": "completed",
                        "output": "Finished safely",
                        "usage": {
                            "input_tokens": 4,
                            "output_tokens": 8,
                            "total_tokens": 12,
                        },
                    },
                ),
                # Hermes' documented stop response intentionally contains no
                # upstream run id; the fixed request path carries the binding.
                FakeResponse(200, {"status": "stopping"}),
            ]
        )
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=queue,
        )

        submitted = client.submit_run("Do the work")
        terminal = client.get_run(REMOTE_RUN_ID)
        stopped = client.stop_run(REMOTE_RUN_ID)

        self.assertEqual(submitted["run_id"], REMOTE_RUN_ID)
        self.assertEqual(terminal["status"], "completed")
        self.assertEqual(terminal["session_id"], "session_" + ("d" * 32))
        self.assertEqual(terminal["usage"]["total_tokens"], 12)
        self.assertEqual(stopped, {"status": "stopping"})
        self.assertEqual(
            [(call["method"], call["path"]) for call in queue.calls],
            [
                ("POST", "/v1/runs"),
                ("GET", f"/v1/runs/{REMOTE_RUN_ID}"),
                ("POST", f"/v1/runs/{REMOTE_RUN_ID}/stop"),
            ],
        )
        self.assertEqual(
            json.loads(queue.calls[0]["body"].decode("utf-8")),
            {"input": "Do the work"},
        )
        self.assertTrue(
            all(call["headers"]["Authorization"] == f"Bearer {SECRET}" for call in queue.calls)
        )
        self.assertEqual(queue.timeouts, [remote_hermes.DEFAULT_TIMEOUT_SECONDS] * 3)

        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_path_not_allowed"):
            client._run_json_request("DELETE", "/v1/runs", expected_status=200)

        for status, expected_error in (
            (400, "remote_run_rejected"),
            (429, "remote_submission_unverified"),
            (500, "remote_submission_unverified"),
            (502, "remote_submission_unverified"),
        ):
            status_queue = ResponseQueue([FakeResponse(status, {})])
            with self.subTest(status=status), self.assertRaisesRegex(
                remote_hermes.RemoteHermesError,
                expected_error,
            ):
                remote_hermes.RemoteHermesClient(
                    ENDPOINT,
                    SECRET,
                    connection_factory=status_queue,
                ).submit_run("Status classification")

        waiting_queue = ResponseQueue([
            FakeResponse(
                200,
                {
                    "object": "hermes.run",
                    "run_id": REMOTE_RUN_ID,
                    "session_id": "session_" + ("d" * 32),
                    "status": "waiting_for_clarification",
                },
            )
        ])
        waiting = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=waiting_queue,
        ).get_run(REMOTE_RUN_ID)
        self.assertEqual(waiting["status"], "waiting_for_clarification")

        no_session_queue = ResponseQueue([
            FakeResponse(
                200,
                {
                    "object": "hermes.run",
                    "run_id": REMOTE_RUN_ID,
                    "status": "running",
                },
            )
        ])
        without_session = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=no_session_queue,
        ).get_run(REMOTE_RUN_ID)
        self.assertEqual(without_session, {"status": "running"})

        for invalid_session_id in (None, "", "/private/session", "session\nchanged"):
            invalid_queue = ResponseQueue([
                FakeResponse(
                    200,
                    {
                        "object": "hermes.run",
                        "run_id": REMOTE_RUN_ID,
                        "session_id": invalid_session_id,
                        "status": "running",
                    },
                )
            ])
            with self.subTest(invalid_session_id=invalid_session_id), self.assertRaisesRegex(
                remote_hermes.RemoteHermesError,
                "remote_run_schema_invalid",
            ):
                remote_hermes.RemoteHermesClient(
                    ENDPOINT,
                    SECRET,
                    connection_factory=invalid_queue,
                ).get_run(REMOTE_RUN_ID)

        for returned_id, accepted in (
            (REMOTE_RUN_ID, True),
            ("run_" + ("c" * 32), False),
        ):
            stop_queue = ResponseQueue([
                FakeResponse(200, {"run_id": returned_id, "status": "stopping"})
            ])
            stop_client = remote_hermes.RemoteHermesClient(
                ENDPOINT,
                SECRET,
                connection_factory=stop_queue,
            )
            if accepted:
                self.assertEqual(stop_client.stop_run(REMOTE_RUN_ID), {"status": "stopping"})
            else:
                with self.assertRaises(remote_hermes.RemoteHermesError):
                    stop_client.stop_run(REMOTE_RUN_ID)

    def test_verified_extension_contracts_use_only_fixed_bound_requests(self):
        capabilities = capability_payload(
            profile_inventory=True,
            profile_inventory_version=1,
            profile_inventory_complete=True,
            profile_inventory_requires_api_key=True,
            run_session_continuation=True,
            run_session_continuation_version=1,
            run_session_continuation_exact_revision=True,
            run_session_continuation_stoppable=True,
            run_approval_response=True,
            run_approval_request_binding=True,
            run_approval_structured_preview=True,
            run_approval_preview_version=1,
            run_clarification_response=True,
            run_clarification_request_binding=True,
            clarification_events=True,
            run_clarification_prompt_version=1,
            run_inline_images=True,
            run_inline_images_version=1,
            run_inline_images_data_urls_only=True,
            run_inline_images_max_count=4,
            run_inline_images_max_bytes=5 * 1024 * 1024,
        )
        capabilities["endpoints"].update({
            "profiles": {"method": "GET", "path": "/v1/profiles"},
            "session_continuation": {"method": "GET", "path": "/v1/sessions/{session_id}/continuation"},
            "run_approval": {"method": "POST", "path": "/v1/runs/{run_id}/approval"},
            "run_clarification": {"method": "POST", "path": "/v1/runs/{run_id}/clarification"},
            "run_inline_images": {"method": "POST", "path": "/v1/runs", "version": 1, "image_transport": "data_url_only", "max_count": 4, "max_bytes_per_image": 5 * 1024 * 1024},
        })
        session_id = "session_" + "b" * 32
        revision = "sessionrev_" + "c" * 64
        approval_id = "approval_1"
        clarification_id = "clarify_1"
        image = (
            "data:image/png;base64,"
            + base64.b64encode(b"a" * 300_000).decode("ascii")
        )
        queue = ResponseQueue([
            FakeResponse(200, capabilities),
            FakeResponse(200, {"object": "list", "version": 1, "complete": True, "active_profile": "default", "data": [{"id": "default", "object": "hermes.profile", "is_default": True, "is_active": True, "served": True}]}),
            FakeResponse(200, capabilities),
            FakeResponse(200, {"object": "hermes.session.continuation", "version": 1, "session_id": session_id, "revision": revision}),
            FakeResponse(200, capabilities),
            FakeResponse(202, {"run_id": REMOTE_RUN_ID, "status": "started"}),
            FakeResponse(200, capabilities),
            FakeResponse(200, {"object": "hermes.run.approval_response", "run_id": REMOTE_RUN_ID, "request_id": approval_id, "choice": "once", "resolved": 1}),
            FakeResponse(200, capabilities),
            FakeResponse(200, {"object": "hermes.run.clarification_response", "run_id": REMOTE_RUN_ID, "request_id": clarification_id, "type": "text"}),
            FakeResponse(200, capabilities),
            FakeResponse(202, {"run_id": REMOTE_RUN_ID, "status": "started"}),
        ])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)

        self.assertEqual(client.read_profiles()[0]["id"], "default")
        descriptor = client.get_continuation_descriptor(session_id)
        self.assertEqual(client.submit_continuation("Continue safely", descriptor)["status"], "started")
        self.assertEqual(client.respond_to_approval(REMOTE_RUN_ID, approval_id, "once")["choice"], "once")
        self.assertEqual(client.respond_to_clarification(REMOTE_RUN_ID, clarification_id, {"type": "text", "text": "Use the safe option"})["type"], "text")
        self.assertEqual(client.submit_run_with_images("Inspect", [image])["status"], "started")
        self.assertEqual(
            [(call["method"], call["path"]) for call in queue.calls],
            [
                ("GET", "/v1/capabilities"), ("GET", "/v1/profiles"),
                ("GET", "/v1/capabilities"), ("GET", f"/v1/sessions/{session_id}/continuation"),
                ("GET", "/v1/capabilities"), ("POST", "/v1/runs"),
                ("GET", "/v1/capabilities"), ("POST", f"/v1/runs/{REMOTE_RUN_ID}/approval"),
                ("GET", "/v1/capabilities"), ("POST", f"/v1/runs/{REMOTE_RUN_ID}/clarification"),
                ("GET", "/v1/capabilities"), ("POST", "/v1/runs"),
            ],
        )
        self.assertEqual(json.loads(queue.calls[5]["body"].decode("utf-8"))["continuation"], descriptor)
        self.assertEqual(json.loads(queue.calls[7]["body"].decode("utf-8")), {"request_id": approval_id, "choice": "once"})
        self.assertEqual(json.loads(queue.calls[9]["body"].decode("utf-8"))["response"]["text"], "Use the safe option")
        self.assertEqual(json.loads(queue.calls[11]["body"].decode("utf-8"))["input"][1]["image_url"], image)
        self.assertGreater(
            len(queue.calls[11]["body"]),
            remote_hermes.MAX_RESPONSE_BYTES,
        )

    def test_interactive_events_reject_private_reflection_before_reaching_the_browser(self):
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=ResponseQueue([]))
        approval = {
            "event": "approval.request", "run_id": REMOTE_RUN_ID, "request_id": "approval_1",
            "preview": {"version": 1, "category": "write", "title": "Save", "summary": "password=private-value", "risk_labels": []},
            "choices": ["once", "deny"],
        }
        clarification = {
            "event": "clarify.request", "run_id": REMOTE_RUN_ID, "request_id": "clarify_1",
            "prompt": {"version": 1, "type": "choice", "question": "Choose", "choices": [{"id": "choice-1", "label": "/private/path"}]},
        }
        for event in (approval, clarification):
            with self.subTest(event=event["event"]), self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_private_reflection"):
                client._normalize_run_event(event, REMOTE_RUN_ID)

    def test_sse_events_are_bounded_normalized_and_hide_upstream_identity(self):
        long_delta = "d" * 5_000
        long_output = "o" * 5_000
        events = [
            {"event": "message.delta", "run_id": REMOTE_RUN_ID, "timestamp": 1, "delta": long_delta},
            {"event": "tool.started", "run_id": REMOTE_RUN_ID, "timestamp": 2, "tool": "read_file", "preview": "/private/path"},
            {"event": "tool.completed", "run_id": REMOTE_RUN_ID, "timestamp": 3, "tool": "read_file", "duration": 1.2},
            {"event": "run.completed", "run_id": REMOTE_RUN_ID, "timestamp": 4, "output": long_output},
        ]
        raw = b"".join(
            b"data: " + json.dumps(event).encode("utf-8") + b"\n\n"
            for event in events
        ) + b": stream closed\n\n"
        queue = ResponseQueue(
            [FakeResponse(200, raw, content_type="text/event-stream", headers={"Content-Length": None})]
        )
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=queue,
        )

        normalized = list(client.iter_run_events(REMOTE_RUN_ID))

        self.assertEqual([event["type"] for event in normalized], [
            "message.delta",
            "tool.started",
            "tool.completed",
            "run.completed",
        ])
        public = json.dumps(normalized)
        self.assertNotIn(REMOTE_RUN_ID, public)
        self.assertNotIn("/private/path", public)
        self.assertNotIn(ENDPOINT, public)
        self.assertNotIn(SECRET, public)
        self.assertEqual(normalized[0]["delta"], long_delta)
        self.assertEqual(normalized[-1]["output"], long_output)
        self.assertEqual(queue.timeouts, [remote_hermes.RUN_STREAM_READ_TIMEOUT_SECONDS])

    def test_replay_cursor_is_authenticated_and_sequences_are_verified(self):
        capabilities = capability_payload(
            run_event_replay=True,
            run_event_replay_version=1,
        )
        events = [
            {
                "event": "runtime.updated",
                "run_id": REMOTE_RUN_ID,
                "provider": "openrouter",
                "model": "anthropic/claude-sonnet-4",
                "sequence": 3,
                "event_id": 3,
            },
            {
                "event": "run.completed",
                "run_id": REMOTE_RUN_ID,
                "output": "done",
                "sequence": 4,
                "event_id": 4,
            },
        ]
        raw = b"".join(
            f"id: {event['sequence']}\ndata: {json.dumps(event)}\n\n".encode("utf-8")
            for event in events
        )
        responses = ResponseQueue([
            FakeResponse(200, {"status": "ok"}),
            FakeResponse(200, health_payload()),
            FakeResponse(200, capabilities),
            FakeResponse(
                200,
                raw,
                content_type="text/event-stream",
                headers={"Content-Length": None},
            ),
        ])
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT, SECRET, connection_factory=responses
        )
        client.require_console_run_capabilities()
        normalized = list(
            client.iter_run_events(REMOTE_RUN_ID, last_event_id=2)
        )
        self.assertEqual([event["sequence"] for event in normalized], [3, 4])
        self.assertEqual(
            normalized[0]["runtime"],
            {
                "provider": "openrouter",
                "model": "anthropic/claude-sonnet-4",
            },
        )
        self.assertEqual(responses.calls[-1]["headers"]["Last-Event-ID"], "2")
        self.assertEqual(
            responses.calls[-1]["headers"]["Authorization"],
            f"Bearer {SECRET}",
        )

    def test_legacy_approval_ack_is_normalized_for_status_reconciliation(self):
        raw = (
            b"id: 1\n"
            + b"data: "
            + json.dumps({
                "event": "approval.responded",
                "run_id": REMOTE_RUN_ID,
                "choice": "once",
                "resolved": 1,
                "sequence": 1,
                "event_id": 1,
            }).encode()
            + b"\n\n"
        )
        responses = ResponseQueue([
            FakeResponse(
                200,
                raw,
                content_type="text/event-stream",
                headers={"Content-Length": None},
            )
        ])
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=responses,
        )
        client._trusted_feature_cache = frozenset({"run_event_replay"})

        events = list(client.iter_run_events(REMOTE_RUN_ID, last_event_id=0))

        self.assertEqual(events, [{
            "type": "approval.responded",
            "choice": "once",
            "resolved": 1,
            "legacy_unbound": True,
            "sequence": 1,
        }])

    def test_pending_action_status_and_runtime_are_strictly_normalized(self):
        capabilities = capability_payload(
            run_pending_action_status=True,
            run_pending_action_status_version=1,
            run_runtime_identity=True,
            run_runtime_identity_version=1,
        )
        pending = {
            "version": 1,
            "kind": "approval",
            "request_id": "approval_2",
            "preview": {
                "version": 1,
                "category": "write",
                "title": "Save note",
                "summary": "Save the reviewed note",
                "risk_labels": ["write"],
            },
            "choices": ["once", "deny"],
        }
        responses = ResponseQueue([
            FakeResponse(200, {"status": "ok"}),
            FakeResponse(200, health_payload()),
            FakeResponse(200, capabilities),
            FakeResponse(200, {
                "object": "hermes.run",
                "run_id": REMOTE_RUN_ID,
                "status": "waiting_for_approval",
                "runtime": {
                    "provider": "openrouter",
                    "model": "anthropic/claude-sonnet-4",
                },
                "pending_action": pending,
            }),
        ])
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT, SECRET, connection_factory=responses
        )
        client.require_console_run_capabilities()
        status = client.get_run(REMOTE_RUN_ID)
        self.assertEqual(status["pending_action"], pending)
        self.assertEqual(status["runtime"]["provider"], "openrouter")
        self.assertNotIn(REMOTE_RUN_ID, json.dumps(status))

    def test_remote_profile_runtime_inventory_is_complete_and_secret_free(self):
        capabilities = capability_payload(
            profile_runtime_inventory=True,
            profile_runtime_inventory_version=1,
            profile_runtime_inventory_complete=True,
            profile_runtime_inventory_requires_api_key=True,
        )
        capabilities["endpoints"]["profile_runtimes"] = {
            "method": "GET",
            "path": "/v1/profile-runtimes",
        }
        responses = ResponseQueue([
            FakeResponse(200, capabilities),
            FakeResponse(200, {
                "object": "hermes.profile_runtime.list",
                "version": 1,
                "complete": True,
                "data": [
                    {
                        "profile_id": "default",
                        "provider": "openai-codex",
                        "model": "gpt-5.6",
                    },
                    {
                        "profile_id": "researcher",
                        "provider": "openrouter",
                        "model": "anthropic/claude-sonnet-4",
                    },
                ],
            }),
        ])
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT, SECRET, connection_factory=responses
        )
        runtimes = client.read_profile_runtimes()
        self.assertEqual(runtimes["researcher"]["provider"], "openrouter")
        self.assertNotIn(SECRET, json.dumps(runtimes))

    def test_remote_console_load_and_agent_refresh_show_read_only_runtime(self):
        capabilities = {
            "model": "configured fallback",
            "capabilities": [
                "run_submission",
                "run_status",
                "run_events_sse",
                "run_stop",
                "profile_runtime_inventory",
            ],
        }
        client = FakeRunClient(capabilities=capabilities)
        adapter = self.adapter(client)
        with patch.object(
            server,
            "hermes_console_transport",
            return_value=adapter,
        ):
            console = server.agent_console_payload()
            refreshed, status = server.refresh_agent_console_models({
                "agent_id": "researcher",
            })

        default = next(
            agent for agent in console["agents"] if agent["id"] == "default"
        )
        self.assertEqual(default["provider"], "openai-codex")
        self.assertEqual(default["model"], "gpt-5.6")
        self.assertTrue(console["provider_inventory"]["read_only"])
        self.assertFalse(
            console["provider_inventory"]["capabilities"]["providers.switch"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(refreshed["agent_id"], "researcher")
        self.assertEqual(
            refreshed["provider_inventory"]["current_provider"],
            "openrouter",
        )
        self.assertEqual(
            refreshed["provider_inventory"]["current_model"],
            "anthropic/claude-sonnet-4",
        )
        self.assertTrue(refreshed["provider_inventory"]["read_only"])
        self.assertFalse(
            refreshed["provider_inventory"]["capabilities"]["providers.switch"]
        )

    def test_completed_status_accepts_declared_output_bound_not_generic_metadata_bound(self):
        output = "result" * 1_000
        queue = ResponseQueue([
            FakeResponse(200, {
                "object": "hermes.run",
                "run_id": REMOTE_RUN_ID,
                "session_id": "session_" + ("d" * 32),
                "status": "completed",
                "output": output,
            })
        ])
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=queue,
        )
        self.assertEqual(client.get_run(REMOTE_RUN_ID)["output"], output)

        oversized = ResponseQueue([
            FakeResponse(200, {
                "object": "hermes.run",
                "run_id": REMOTE_RUN_ID,
                "session_id": "session_" + ("d" * 32),
                "status": "completed",
                "output": "x" * 200_001,
            })
        ])
        with self.assertRaises(remote_hermes.RemoteHermesError):
            remote_hermes.RemoteHermesClient(
                ENDPOINT,
                SECRET,
                connection_factory=oversized,
            ).get_run(REMOTE_RUN_ID)

        for reflected in (ENDPOINT.split("//", 1)[1], REMOTE_RUN_ID):
            reflected_queue = ResponseQueue([
                FakeResponse(200, {
                    "object": "hermes.run",
                    "run_id": REMOTE_RUN_ID,
                    "session_id": "session_" + ("d" * 32),
                    "status": "completed",
                    "output": f"reflected {reflected}",
                })
            ])
            with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_private_reflection"):
                remote_hermes.RemoteHermesClient(
                    ENDPOINT,
                    SECRET,
                    connection_factory=reflected_queue,
                ).get_run(REMOTE_RUN_ID)

        short_host_queue = ResponseQueue([
            FakeResponse(200, {
                "object": "hermes.run",
                "run_id": REMOTE_RUN_ID,
                "session_id": "session_" + ("d" * 32),
                "status": "completed",
                "output": "Connected to hermes",
            })
        ])
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_private_reflection"):
            remote_hermes.RemoteHermesClient(
                "https://hermes",
                SECRET,
                connection_factory=short_host_queue,
            ).get_run(REMOTE_RUN_ID)

    def test_sse_malformed_reflected_or_wrong_run_events_fail_closed(self):
        payloads = (
            b"data: {broken\n\n",
            b"data: " + json.dumps({"event": "message.delta", "run_id": REMOTE_RUN_ID, "delta": SECRET}).encode() + b"\n\n",
            b"data: " + json.dumps({"event": "run.cancelled", "run_id": "run_" + ("c" * 32)}).encode() + b"\n\n",
            b"field-without-sse-prefix\n\n",
            b"data: " + json.dumps({"event": "message.delta", "run_id": REMOTE_RUN_ID, "delta": "x" * 16_001}).encode() + b"\n\n",
            b"data: " + json.dumps({"event": "message.delta", "run_id": REMOTE_RUN_ID, "delta": "host " + ENDPOINT.split("//", 1)[1]}).encode() + b"\n\n",
            b"data: " + json.dumps({"event": "message.delta", "run_id": REMOTE_RUN_ID, "delta": REMOTE_RUN_ID}).encode() + b"\n\n",
            b"data: " + json.dumps({"event": "tool.started", "run_id": REMOTE_RUN_ID, "tool": REMOTE_RUN_ID}).encode() + b"\n\n",
            b"data: " + json.dumps({"event": "runtime.updated", "run_id": REMOTE_RUN_ID, "provider": "openrouter", "model": "sk-proj-" + ("a" * 32)}).encode() + b"\n\n",
            b"data: " + json.dumps({"event": "runtime.updated", "run_id": REMOTE_RUN_ID, "provider": "openrouter", "model": "openai/sk-proj-" + ("a" * 32)}).encode() + b"\n\n",
        )
        for raw in payloads:
            with self.subTest(raw=raw[:30]):
                queue = ResponseQueue(
                    [FakeResponse(200, raw, content_type="text/event-stream", headers={"Content-Length": None})]
                )
                client = remote_hermes.RemoteHermesClient(
                    ENDPOINT,
                    SECRET,
                    connection_factory=queue,
                )
                with self.assertRaises(remote_hermes.RemoteHermesError):
                    list(client.iter_run_events(REMOTE_RUN_ID))

    def test_sse_keepalives_have_wall_clock_bound_and_many_data_lines_are_linear(self):
        keepalive = ResponseQueue([
            FakeResponse(200, b": keepalive\n\n", content_type="text/event-stream", headers={"Content-Length": None})
        ])
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=keepalive,
        )
        with patch.object(
            remote_hermes.time,
            "monotonic",
            side_effect=[0.0, remote_hermes.RUN_STREAM_MAX_SECONDS + 1.0],
        ), self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_timeout"):
            list(client.iter_run_events(REMOTE_RUN_ID))

        raw = b"data: {\n" + (b"data:  \n" * 2_000) + (
            b'data: "event":"run.cancelled","run_id":"'
            + REMOTE_RUN_ID.encode()
            + b'"}\n\n'
        )
        split_lines = ResponseQueue([
            FakeResponse(200, raw, content_type="text/event-stream", headers={"Content-Length": None})
        ])
        normalized = list(remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=split_lines,
        ).iter_run_events(REMOTE_RUN_ID))
        self.assertEqual(normalized, [{"type": "run.cancelled"}])

    def test_remote_server_run_completes_without_local_fallback_or_public_upstream_id(self):
        client = FakeRunClient(
            events=[
                {"type": "message.delta", "delta": "Working"},
                {"type": "tool.started", "tool": "read_file"},
                {"type": "tool.completed", "tool": "read_file"},
                {"type": "run.completed", "output": "Complete"},
            ],
            statuses=[
                {
                    "status": "completed",
                    "output": "Complete",
                    "usage": {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
                }
            ],
        )
        adapter = self.adapter(client)
        with patch.object(adapter, "revalidate"), patch.object(
            server,
            "hermes_console_transport",
            return_value=adapter,
        ), patch.object(
            server,
            "hermes_profiles_payload",
            side_effect=AssertionError("local profiles must not be read"),
        ), patch.object(
            server,
            "hermes_command_path",
            side_effect=AssertionError("local CLI must not be resolved"),
        ), patch.object(
            server.subprocess,
            "Popen",
            side_effect=AssertionError("local CLI must not launch"),
        ), patch.object(server.threading, "Thread") as worker, patch.object(
            server,
            "persist_agent_console_runs",
        ):
            payload, status = server.start_agent_console_run(
                {"agent_id": "default", "prompt": "Remote work"}
            )
            run_id = payload["run"]["id"]
            server.run_remote_hermes_agent(run_id, adapter)

        self.assertEqual(status, 202)
        worker.return_value.start.assert_called_once_with()
        run = server.AGENT_CONSOLE_RUNS[run_id]
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["response"], "Complete")
        self.assertEqual(run["usage"]["total_tokens"], 8)
        self.assertEqual(client.submitted, ["Remote work"])
        public = json.dumps(server.agent_console_snapshot(run))
        history = json.dumps(agent_run_history.summarize_run(run))
        for private in (REMOTE_RUN_ID, ENDPOINT, SECRET):
            self.assertNotIn(private, public)
            self.assertNotIn(private, history)

    def test_completed_remote_run_projects_session_for_safe_continuation(self):
        upstream_session_id = "session_" + ("d" * 32)
        client = FakeRunClient(
            events=[{"type": "run.completed", "output": "Complete"}],
            statuses=[
                {
                    "status": "completed",
                    "session_id": upstream_session_id,
                    "output": "Complete",
                    "usage": None,
                }
            ],
        )
        adapter = self.adapter(client)
        with patch.object(adapter, "revalidate"), patch.object(
            server,
            "hermes_console_transport",
            return_value=adapter,
        ), patch.object(server.threading, "Thread") as worker, patch.object(
            server,
            "persist_agent_console_runs",
        ):
            payload, status = server.start_agent_console_run(
                {"agent_id": "default", "prompt": "Remote work"}
            )
            run_id = payload["run"]["id"]
            server.run_remote_hermes_agent(run_id, adapter)

        self.assertEqual(status, 202)
        worker.return_value.start.assert_called_once_with()
        public = server.agent_console_snapshot(server.AGENT_CONSOLE_RUNS[run_id])
        alias = public["session_id"]
        self.assertRegex(alias, r"^remote_session_[0-9a-f]{32}$")
        self.assertNotIn(upstream_session_id, json.dumps(public))
        resolved, partial, structural_ids = server._remote_session_id_for_alias(
            adapter.binding.binding_id,
            alias,
        )
        self.assertEqual(resolved, upstream_session_id)
        self.assertFalse(partial)
        self.assertEqual(structural_ids, (upstream_session_id,))

    def test_interrupted_stream_reconciles_from_status_without_resubmission(self):
        client = FakeRunClient(
            events=[remote_hermes.RemoteHermesError("remote_timeout")],
            statuses=[
                {"status": "running"},
                {"status": "completed", "output": "Recovered", "usage": None},
            ],
        )
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_reconcile"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "model": "anthropic/claude-test",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Recover",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(
            server.time,
            "sleep",
        ), patch.object(server, "persist_agent_console_runs"):
            server.run_remote_hermes_agent(run_id, adapter)

        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "completed")
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["response"], "Recovered")
        self.assertEqual(client.submitted, ["Recover"])

    def test_status_error_after_acceptance_stops_and_verifies_terminal_state(self):
        client = FakeRunClient(
            events=[remote_hermes.RemoteHermesError("remote_timeout")],
            statuses=[
                remote_hermes.RemoteHermesError("remote_timeout"),
                {"status": "cancelled"},
            ],
        )
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_status_failure"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "model": "anthropic/claude-test",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Do not orphan",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            server.run_remote_hermes_agent(run_id, adapter)

        run = server.AGENT_CONSOLE_RUNS[run_id]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(client.stopped, [REMOTE_RUN_ID])
        self.assertFalse(run.get("partial", False))
        self.assertNotIn("_remote_run_id", run)

    def test_uncertain_submission_response_is_retained_as_partial(self):
        class UncertainSubmitClient(FakeRunClient):
            def submit_run(self, prompt):
                self.submitted.append(prompt)
                raise remote_hermes.RemoteHermesError("remote_timeout")

        client = UncertainSubmitClient()
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_uncertain_submit"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "model": "anthropic/claude-test",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Maybe accepted",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            server.run_remote_hermes_agent(run_id, adapter)

        run = server.AGENT_CONSOLE_RUNS[run_id]
        self.assertEqual(run["status"], "failed")
        self.assertTrue(run["partial"])
        self.assertIn("whether", run["error"].lower())
        self.assertEqual(client.submitted, ["Maybe accepted"])

    def test_deterministic_submission_rejection_is_not_marked_partial(self):
        class RejectedSubmitClient(FakeRunClient):
            def submit_run(self, prompt):
                self.submitted.append(prompt)
                raise remote_hermes.RemoteHermesError(
                    "remote_run_request_invalid"
                )

        client = RejectedSubmitClient()
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_rejected_submit"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "model": "anthropic/claude-test",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Definitely rejected",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(
            server,
            "persist_agent_console_runs",
        ):
            server.run_remote_hermes_agent(run_id, adapter)

        run = server.AGENT_CONSOLE_RUNS[run_id]
        self.assertEqual(run["status"], "failed")
        self.assertFalse(run.get("partial", False))
        self.assertIn("invalid", run["error"].lower())
        self.assertEqual(
            run["events"][-1]["display_text"],
            "Remote Hermes request failed safely",
        )
        self.assertEqual(client.submitted, ["Definitely rejected"])

    def test_approval_event_stops_and_fails_without_auto_approval(self):
        client = FakeRunClient(
            events=[{"type": "approval.request"}, {"type": "run.cancelled"}],
            statuses=[{"status": "cancelled"}],
        )
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_approval"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "model": "anthropic/claude-test",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Needs approval",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            server.run_remote_hermes_agent(run_id, adapter)

        run = server.AGENT_CONSOLE_RUNS[run_id]
        self.assertEqual(run["status"], "failed")
        self.assertIn("approval", run["error"].lower())
        self.assertEqual(client.stopped, [REMOTE_RUN_ID])

    def test_verified_approval_waits_for_operator_and_resumes_without_resubmission(self):
        client = FakeRunClient(
            events=[{
                "type": "approval.request", "request_id": "approval_1",
                "preview": {"version": 1, "category": "write", "title": "Save note", "summary": "Save the reviewed note", "risk_labels": ["write"]},
                "choices": ["once", "deny"],
            }],
            statuses=[{"status": "waiting_for_approval"}, {"status": "running"}],
        )
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_waiting_approval"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id, "agent_id": "default", "agent_name": "Remote workshop",
            "model": "anthropic/claude-test", "transport_mode": "remote",
            "connection_binding_id": "b" * 32, "prompt": "Needs approval", "status": "queued",
            "session_id": None, "response": "", "error": "", "events": [], "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            server.run_remote_hermes_agent(run_id, adapter)
            waiting = server.AGENT_CONSOLE_RUNS[run_id]
            self.assertEqual(waiting["status"], "waiting_for_approval")
            self.assertEqual(client.stopped, [])
            with patch.object(server.threading, "Thread") as worker:
                response, status = server.respond_to_remote_console_action(run_id, {
                    "confirmed": True, "kind": "approval", "request_id": "approval_1", "choice": "once",
                })
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertEqual(client.approvals, [("approval_1", "once")])
        self.assertEqual(client.submitted, ["Needs approval"])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "queued")
        worker.return_value.start.assert_called_once_with()

    def test_one_stream_survives_approval_then_clarification_until_completion(self):
        class InteractiveRunClient(FakeRunClient):
            def __init__(self):
                super().__init__()
                self.stream_events = queue.Queue()
                self.stream_started = threading.Event()
                self.current_status = {"status": "running"}
                self.stream_events.put({
                    "type": "approval.request",
                    "request_id": "approval_1",
                    "preview": {
                        "version": 1,
                        "category": "write",
                        "title": "Save note",
                        "summary": "Save the reviewed note",
                        "risk_labels": ["write"],
                    },
                    "choices": ["once", "deny"],
                })

            def iter_run_events(self, run_id, *, should_stop=None, last_event_id=None):
                self.assert_run_id(run_id)
                self.iter_calls += 1
                self.last_event_ids.append(last_event_id)
                self.stream_started.set()
                while should_stop is None or not should_stop():
                    event = self.stream_events.get(timeout=2)
                    yield event
                    if event.get("type") in {"run.completed", "run.failed", "run.cancelled"}:
                        return

            def get_run(self, run_id):
                self.assert_run_id(run_id)
                return dict(self.current_status)

            def respond_to_approval(self, run_id, request_id, choice):
                result = super().respond_to_approval(run_id, request_id, choice)
                self.current_status = {"status": "running"}
                self.stream_events.put({
                    "type": "approval.responded",
                    "request_id": request_id,
                    "choice": choice,
                    "resolved": 1,
                })
                self.stream_events.put({
                    "type": "clarify.request",
                    "request_id": "clarify_1",
                    "prompt": {
                        "version": 1,
                        "type": "choice",
                        "question": "Which format?",
                        "choices": [
                            {"id": "choice-1", "label": "Markdown"},
                            {"id": "choice-2", "label": "Plain text"},
                        ],
                    },
                })
                return result

            def respond_to_clarification(self, run_id, request_id, response):
                result = super().respond_to_clarification(
                    run_id,
                    request_id,
                    response,
                )
                self.stream_events.put({
                    "type": "clarify.responded",
                    "request_id": request_id,
                    "response_type": response["type"],
                })
                self.current_status = {
                    "status": "completed",
                    "output": "Saved as Markdown.",
                }
                self.stream_events.put({
                    "type": "run.completed",
                    "output": "Saved as Markdown.",
                })
                return result

        def wait_for_status(run_id, expected):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with server.AGENT_CONSOLE_LOCK:
                    current = server.AGENT_CONSOLE_RUNS.get(run_id, {})
                    if current.get("status") == expected:
                        return dict(current)
                time.sleep(0.01)
            self.fail(f"run did not reach {expected}")

        client = InteractiveRunClient()
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_persistent_interactions"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "model": "anthropic/claude-test",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Save this note",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        worker = threading.Thread(
            target=server.run_remote_hermes_agent,
            args=(run_id, adapter),
            daemon=True,
        )
        with patch.object(adapter, "revalidate"), patch.object(
            server,
            "persist_agent_console_runs",
        ):
            worker.start()
            self.assertTrue(client.stream_started.wait(1))
            wait_for_status(run_id, "waiting_for_approval")
            response, status = server.respond_to_remote_console_action(run_id, {
                "confirmed": True,
                "kind": "approval",
                "request_id": "approval_1",
                "choice": "once",
            })
            self.assertEqual(status, 200)
            self.assertTrue(response["ok"])
            clarification = wait_for_status(run_id, "waiting_for_clarification")
            self.assertEqual(
                clarification["action_required"]["request_id"],
                "clarify_1",
            )
            response, status = server.respond_to_remote_console_action(run_id, {
                "confirmed": True,
                "kind": "clarification",
                "request_id": "clarify_1",
                "response": {"type": "choice", "choice_id": "choice-1"},
            })
            self.assertEqual(status, 200)
            self.assertTrue(response["ok"])
            worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(client.iter_calls, 1)
        self.assertEqual(client.submitted, ["Save this note"])
        self.assertEqual(client.approvals, [("approval_1", "once")])
        self.assertEqual(
            client.clarifications,
            [("clarify_1", {"type": "choice", "choice_id": "choice-1"})],
        )
        self.assertEqual(
            server.AGENT_CONSOLE_RUNS[run_id]["status"],
            "completed",
        )
        self.assertEqual(
            server.AGENT_CONSOLE_RUNS[run_id]["response"],
            "Saved as Markdown.",
        )

    def test_dropped_replay_stream_reconnects_from_cursor_without_resubmission(self):
        class ReconnectingRunClient(FakeRunClient):
            def __init__(self):
                super().__init__(
                    capabilities={
                        "model": "anthropic/claude-test",
                        "capabilities": [
                            "run_submission",
                            "run_status",
                            "run_events_sse",
                            "run_event_replay",
                            "run_stop",
                        ],
                    }
                )
                self.current_status = {"status": "running"}

            def iter_run_events(self, run_id, *, should_stop=None, last_event_id=None):
                self.assert_run_id(run_id)
                self.iter_calls += 1
                self.last_event_ids.append(last_event_id)
                if self.iter_calls == 1:
                    yield {
                        "type": "tool.started",
                        "tool": "web_search",
                        "sequence": 1,
                    }
                    return
                self.current_status = {
                    "status": "completed",
                    "output": "Recovered after reconnect.",
                }
                yield {
                    "type": "run.completed",
                    "output": "Recovered after reconnect.",
                    "sequence": 2,
                }

            def get_run(self, run_id):
                self.assert_run_id(run_id)
                return dict(self.current_status)

        client = ReconnectingRunClient()
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_replay_reconnect"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "provider": "",
            "model": "",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Continue after a dropped stream",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(
            server, "persist_agent_console_runs"
        ):
            server.run_remote_hermes_agent(run_id, adapter)

        self.assertEqual(client.iter_calls, 2)
        self.assertEqual(client.last_event_ids, [0, 1])
        self.assertEqual(client.submitted, ["Continue after a dropped stream"])
        self.assertEqual(client.stopped, [])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "completed")
        self.assertEqual(
            server.AGENT_CONSOLE_RUNS[run_id]["response"],
            "Recovered after reconnect.",
        )

    def test_duplicate_only_replay_does_not_reset_bounded_reconnect_attempts(self):
        class DuplicateReplayClient(FakeRunClient):
            def __init__(self):
                super().__init__(
                    capabilities={
                        "model": "anthropic/claude-test",
                        "capabilities": [
                            "run_submission",
                            "run_status",
                            "run_events_sse",
                            "run_event_replay",
                            "run_stop",
                        ],
                    }
                )
                self.status_calls = 0

            def iter_run_events(self, run_id, *, should_stop=None, last_event_id=None):
                self.assert_run_id(run_id)
                self.iter_calls += 1
                self.last_event_ids.append(last_event_id)
                yield {
                    "type": "tool.started",
                    "tool": "web_search",
                    "sequence": 1,
                }

            def get_run(self, run_id):
                self.assert_run_id(run_id)
                self.status_calls += 1
                if self.status_calls <= 2:
                    return {"status": "running"}
                return {
                    "status": "completed",
                    "output": "Completed after bounded duplicate replay.",
                }

        client = DuplicateReplayClient()
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_duplicate_replay"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "provider": "openrouter",
            "model": "anthropic/claude-test",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Do not reconnect forever",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
            "_remote_event_cursor": 1,
            "_remote_run_id": REMOTE_RUN_ID,
            "_remote_transport": adapter,
        }
        with patch.object(adapter, "revalidate"), patch.object(
            server, "persist_agent_console_runs"
        ), patch.object(
            server, "REMOTE_CONSOLE_STREAM_RECONNECT_ATTEMPTS", 1
        ):
            server.run_remote_hermes_agent(run_id, adapter)

        self.assertEqual(client.iter_calls, 2)
        self.assertEqual(client.last_event_ids, [1, 1])
        self.assertEqual(client.submitted, [])
        self.assertEqual(client.stopped, [])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "completed")

    def test_replay_sequence_must_begin_immediately_after_cursor_zero(self):
        run_id = "run_remote_sequence_prefix"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "status": "running",
            "events": [],
            "_remote_event_cursor": 0,
        }
        with patch.object(server, "persist_agent_console_runs"):
            should_stop = server._apply_remote_console_event(run_id, {
                "type": "tool.started",
                "tool": "web_search",
                "sequence": 2,
            })
        self.assertTrue(should_stop)
        self.assertEqual(
            server.AGENT_CONSOLE_RUNS[run_id]["_remote_event_cursor"],
            0,
        )
        self.assertIn(
            "continuity could not be verified",
            server.AGENT_CONSOLE_RUNS[run_id]["events"][-1]["message"],
        )

    def test_legacy_approval_ack_reconciles_authoritative_status(self):
        class LegacyAckClient(FakeRunClient):
            def __init__(self):
                super().__init__(
                    events=[
                        {
                            "type": "approval.request",
                            "request_id": "approval_legacy",
                            "preview": {
                                "version": 1,
                                "category": "protected_action",
                                "title": "Protected action approval",
                                "summary": "Hermes stopped an action that requires explicit approval.",
                                "risk_labels": [],
                            },
                            "choices": ["once", "deny"],
                            "sequence": 1,
                        },
                        {
                            "type": "approval.responded",
                            "choice": "once",
                            "resolved": 1,
                            "legacy_unbound": True,
                            "sequence": 2,
                        },
                        {
                            "type": "run.completed",
                            "output": "Resolved by a legacy controller.",
                            "sequence": 3,
                        },
                    ],
                    capabilities={
                        "model": "anthropic/claude-test",
                        "capabilities": [
                            "run_submission",
                            "run_status",
                            "run_events_sse",
                            "run_event_replay",
                            "run_pending_action_status",
                            "run_stop",
                        ],
                    },
                )
                self.status_calls = 0

            def get_run(self, run_id):
                self.assert_run_id(run_id)
                self.status_calls += 1
                if self.status_calls == 1:
                    return {"status": "running"}
                return {
                    "status": "completed",
                    "output": "Resolved by a legacy controller.",
                }

        client = LegacyAckClient()
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_legacy_ack"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "provider": "",
            "model": "",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Wait for an external approval",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(
            server, "persist_agent_console_runs"
        ):
            server.run_remote_hermes_agent(run_id, adapter)

        self.assertEqual(client.stopped, [])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "completed")
        self.assertNotIn(
            "action_required",
            server.AGENT_CONSOLE_RUNS[run_id],
        )

    def test_clarification_response_must_match_the_current_prompt(self):
        client = FakeRunClient(statuses=[])
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_waiting_choice"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id, "transport_mode": "remote", "connection_binding_id": "b" * 32,
            "status": "waiting_for_clarification", "events": [], "_remote_run_id": REMOTE_RUN_ID,
            "_remote_transport": adapter,
            "action_required": {"kind": "clarification", "request_id": "clarify_1", "prompt": {"version": 1, "type": "choice", "question": "Proceed?", "choices": [{"id": "choice-1", "label": "Yes"}]}},
        }
        with patch.object(adapter, "revalidate"):
            response, status = server.respond_to_remote_console_action(run_id, {
                "confirmed": True, "kind": "clarification", "request_id": "clarify_1",
                "response": {"type": "choice", "choice_id": "choice-2"},
            })
        self.assertEqual(status, 400)
        self.assertIn("current remote options", response["error"])
        self.assertEqual(client.clarifications, [])

    def test_response_stays_pending_when_hermes_has_not_verified_resume(self):
        client = FakeRunClient(statuses=[{"status": "waiting_for_approval"}])
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_remote_response_pending"
        action = {"kind": "approval", "request_id": "approval_1", "preview": {"version": 1}, "choices": ["once", "deny"]}
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id, "transport_mode": "remote", "connection_binding_id": "b" * 32,
            "status": "waiting_for_approval", "events": [], "_remote_run_id": REMOTE_RUN_ID,
            "_remote_transport": adapter, "action_required": action,
        }
        with patch.object(adapter, "revalidate"):
            response, status = server.respond_to_remote_console_action(run_id, {
                "confirmed": True, "kind": "approval", "request_id": "approval_1", "choice": "once",
            })
        self.assertEqual(status, 502)
        self.assertTrue(response["partial"])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["action_required"], action)
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "waiting_for_approval")

    def test_interrupted_stream_surfaces_approval_status_and_verifies_true_terminal(self):
        client = FakeRunClient(
            events=[remote_hermes.RemoteHermesError("remote_timeout")],
            statuses=[
                {"status": "waiting_for_approval"},
                {"status": "waiting_for_approval"},
                {"status": "cancelled"},
            ],
        )
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_approval_status"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "Remote workshop",
            "model": "anthropic/claude-test",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "prompt": "Approval fallback",
            "status": "queued",
            "session_id": None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(server.time, "sleep"), patch.object(
            server,
            "persist_agent_console_runs",
        ):
            server.run_remote_hermes_agent(run_id, adapter)

        run = server.AGENT_CONSOLE_RUNS[run_id]
        self.assertEqual(run["status"], "failed")
        self.assertIn("approval", run["error"].lower())
        self.assertFalse(run.get("partial", False))
        self.assertEqual(client.stopped, [REMOTE_RUN_ID])
        self.assertEqual(client.statuses, [])

    def test_remote_cancel_uses_private_bound_stop_reference(self):
        client = FakeRunClient()
        adapter = self.adapter(client)
        adapter.prepare_console()
        server.AGENT_CONSOLE_RUNS["run_cancel"] = {
            "id": "run_cancel",
            "status": "running",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "_remote_run_id": REMOTE_RUN_ID,
            "_remote_transport": adapter,
        }
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            payload, status = server.cancel_agent_console_run("run_cancel")

        self.assertEqual(status, 202)
        self.assertTrue(payload["ok"])
        self.assertEqual(client.stopped, [REMOTE_RUN_ID])
        self.assertNotIn(REMOTE_RUN_ID, json.dumps(payload))

        # A later approval or timeout path cannot race cancellation into a
        # second stop request for the same bound run.
        stopped_again = server._request_remote_console_stop_once(
            "run_cancel",
            adapter,
            REMOTE_RUN_ID,
        )
        self.assertFalse(stopped_again)
        self.assertEqual(client.stopped, [REMOTE_RUN_ID])

    def test_unverified_remote_stop_is_partial_and_never_retried(self):
        class FailingStopClient(FakeRunClient):
            def stop_run(self, run_id):
                self.assert_run_id(run_id)
                self.stopped.append(run_id)
                raise remote_hermes.RemoteHermesError("remote_timeout")

        client = FailingStopClient(
            statuses=[remote_hermes.RemoteHermesError("remote_timeout")]
        )
        adapter = self.adapter(client)
        adapter.prepare_console()
        server.AGENT_CONSOLE_RUNS["run_stop_failure"] = {
            "id": "run_stop_failure",
            "status": "running",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "_remote_run_id": REMOTE_RUN_ID,
            "_remote_transport": adapter,
        }
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            payload, status = server.cancel_agent_console_run("run_stop_failure")
            second, second_status = server.cancel_agent_console_run("run_stop_failure")

        self.assertEqual(status, 502)
        self.assertEqual(second_status, 502)
        self.assertTrue(payload["partial"])
        self.assertTrue(second["partial"])
        self.assertEqual(client.stopped, [REMOTE_RUN_ID])
        self.assertNotIn(REMOTE_RUN_ID, json.dumps(payload))

        running_client = FailingStopClient(statuses=[{"status": "running"}])
        running_adapter = self.adapter(running_client)
        running_adapter.prepare_console()
        server.AGENT_CONSOLE_RUNS["run_stop_still_running"] = {
            "id": "run_stop_still_running",
            "status": "running",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "_remote_run_id": REMOTE_RUN_ID,
            "_remote_transport": running_adapter,
        }
        with patch.object(running_adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            running_payload, running_status = server.cancel_agent_console_run(
                "run_stop_still_running"
            )
        self.assertEqual(running_status, 502)
        self.assertTrue(running_payload["partial"])

    def test_cancel_terminal_race_uses_verified_upstream_status(self):
        class CompletedRaceClient(FakeRunClient):
            def stop_run(self, run_id):
                self.assert_run_id(run_id)
                self.stopped.append(run_id)
                raise remote_hermes.RemoteHermesError("remote_run_rejected")

        client = CompletedRaceClient(statuses=[{
            "status": "completed",
            "output": "Won the race",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }])
        adapter = self.adapter(client)
        adapter.prepare_console()
        server.AGENT_CONSOLE_RUNS["run_cancel_race"] = {
            "id": "run_cancel_race",
            "status": "running",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
            "_remote_run_id": REMOTE_RUN_ID,
            "_remote_transport": adapter,
        }
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            payload, status = server.cancel_agent_console_run("run_cancel_race")

        self.assertEqual(status, 409)
        self.assertEqual(payload["run"]["status"], "completed")
        self.assertEqual(payload["run"]["response"], "Won the race")
        self.assertFalse(payload["run"].get("partial", False))
        self.assertTrue(payload["run"].get("completed_at"))
        self.assertTrue(server._remote_console_stream_should_stop("run_cancel_race"))

        # An SSE iterator may already have received another delta when the
        # cancellation read-back wins the race. Inactive runs are immutable.
        applied = server._apply_remote_console_event(
            "run_cancel_race",
            {"type": "message.delta", "delta": " late and stale"},
        )
        self.assertFalse(applied)
        self.assertEqual(
            server.AGENT_CONSOLE_RUNS["run_cancel_race"]["response"],
            "Won the race",
        )
        self.assertNotIn("_remote_run_id", server.AGENT_CONSOLE_RUNS["run_cancel_race"])
        self.assertNotIn("_remote_transport", server.AGENT_CONSOLE_RUNS["run_cancel_race"])

    def test_shutdown_verifies_remote_terminal_or_records_partial(self):
        cases = (
            (FakeRunClient(statuses=[{"status": "cancelled"}]), "cancelled", False),
            (FakeRunClient(statuses=[remote_hermes.RemoteHermesError("remote_timeout")]), "failed", True),
        )
        for index, (client, expected_status, expected_partial) in enumerate(cases):
            with self.subTest(expected_status=expected_status):
                server.AGENT_CONSOLE_RUNS.clear()
                adapter = self.adapter(client)
                adapter.prepare_console()
                run_id = f"run_shutdown_{index}"
                server.AGENT_CONSOLE_RUNS[run_id] = {
                    "id": run_id,
                    "status": "running",
                    "events": [],
                    "created_at": "2026-07-20T00:00:00-07:00",
                    "transport_mode": "remote",
                    "connection_binding_id": "b" * 32,
                    "_remote_run_id": REMOTE_RUN_ID,
                    "_remote_transport": adapter,
                }
                with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
                    server.stop_agent_console_processes()
                run = server.AGENT_CONSOLE_RUNS[run_id]
                self.assertEqual(run["status"], expected_status)
                self.assertEqual(bool(run.get("partial")), expected_partial)

        server.AGENT_CONSOLE_RUNS.clear()
        finished_worker = server.threading.Thread(target=lambda: None)
        finished_worker.start()
        finished_worker.join()
        server.AGENT_CONSOLE_RUNS["run_submit_window"] = {
            "id": "run_submit_window",
            "status": "running",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
        }
        server.AGENT_CONSOLE_REMOTE_WORKERS["run_submit_window"] = finished_worker
        with patch.object(server, "persist_agent_console_runs"):
            server.stop_agent_console_processes()
        self.assertEqual(server.AGENT_CONSOLE_RUNS["run_submit_window"]["status"], "failed")
        self.assertTrue(server.AGENT_CONSOLE_RUNS["run_submit_window"]["partial"])

        delayed_client = FakeRunClient()
        delayed_adapter = self.adapter(delayed_client)
        delayed_adapter.prepare_console()
        with patch.object(delayed_adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            server.run_remote_hermes_agent("run_submit_window", delayed_adapter)
        self.assertEqual(delayed_client.submitted, [])
        self.assertEqual(server.AGENT_CONSOLE_RUNS["run_submit_window"]["status"], "failed")

        server.AGENT_CONSOLE_RUNS.clear()
        unstarted = server.threading.Thread(target=lambda: None)
        server.AGENT_CONSOLE_RUNS["run_unstarted_worker"] = {
            "id": "run_unstarted_worker",
            "status": "queued",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
            "transport_mode": "remote",
            "connection_binding_id": "b" * 32,
        }
        server.AGENT_CONSOLE_REMOTE_WORKERS["run_unstarted_worker"] = unstarted
        with patch.object(server, "persist_agent_console_runs"):
            server.stop_agent_console_processes()
        self.assertTrue(server.AGENT_CONSOLE_RUNS["run_unstarted_worker"]["partial"])

    def test_binding_mismatch_fails_before_remote_submission(self):
        client = FakeRunClient()
        adapter = self.adapter(client)
        adapter.prepare_console()
        run_id = "run_wrong_binding"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "transport_mode": "remote",
            "connection_binding_id": "c" * 32,
            "prompt": "Do not submit",
            "status": "queued",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            server.run_remote_hermes_agent(run_id, adapter)

        self.assertEqual(client.submitted, [])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "failed")

    def test_remote_history_retention_and_usage_partial_round_trip(self):
        for index in range(server.AGENT_CONSOLE_RUN_LIMIT):
            server.AGENT_CONSOLE_RUNS[f"old_{index:02d}"] = {
                "id": f"old_{index:02d}",
                "status": "completed",
                "created_at": f"2026-07-19T00:{index:02d}:00-07:00",
                "transport_mode": "local",
                "connection_binding_id": "local-default",
                "events": [],
            }
        adapter = self.adapter()
        with patch.object(adapter, "revalidate"), patch.object(
            server,
            "hermes_console_transport",
            return_value=adapter,
        ), patch.object(server.threading, "Thread"), patch.object(
            server,
            "persist_agent_console_runs",
        ), patch.object(server, "unbind_run_attachments"):
            payload, status = server.start_agent_console_run(
                {"agent_id": "default", "prompt": "Retained remote work"}
            )

        self.assertEqual(status, 202)
        self.assertEqual(len(server.AGENT_CONSOLE_RUNS), server.AGENT_CONSOLE_RUN_LIMIT)
        self.assertIn(payload["run"]["id"], server.AGENT_CONSOLE_RUNS)

        run = server.AGENT_CONSOLE_RUNS[payload["run"]["id"]]
        run.update({
            "status": "failed",
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
            "partial": True,
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            agent_run_history.save_run_summaries(path, [run])
            restored, _ = agent_run_history.load_run_summaries(path)
        self.assertEqual(restored[0]["usage"]["total_tokens"], 3)
        self.assertTrue(restored[0]["partial"])

        active_remote = {
            **run,
            "id": "run_restart_remote",
            "status": "running",
            "partial": False,
            "error": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            agent_run_history.save_run_summaries(path, [active_remote])
            recovered, changed = agent_run_history.load_run_summaries(path)
        self.assertTrue(changed)
        self.assertEqual(recovered[0]["status"], "interrupted")
        self.assertTrue(recovered[0]["partial"])
        self.assertIn("could not be verified", recovered[0]["error"])

    def test_remote_start_rejects_deferred_inputs_before_submission(self):
        client = FakeRunClient()
        adapter = self.adapter(client)
        cases = (
            ({"agent_id": "researcher", "prompt": "Work"}, "profile"),
            ({"agent_id": "default", "prompt": "Work", "attachment_ids": ["attachment_" + ("a" * 32)]}, "attachments"),
            ({"agent_id": "default", "prompt": "Work", "session_id": "session_1"}, "session"),
        )
        with patch.object(server, "hermes_console_transport", return_value=adapter), patch.object(
            adapter, "revalidate"
        ), patch.object(
            server,
            "persist_agent_console_runs",
        ):
            for request, word in cases:
                with self.subTest(word=word):
                    payload, status = server.start_agent_console_run(request)
                    self.assertEqual(status, 409)
                    self.assertIn(word, payload["error"].lower())
        self.assertEqual(client.submitted, [])


if __name__ == "__main__":
    unittest.main()
