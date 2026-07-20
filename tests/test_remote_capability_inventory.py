from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from hermes_transport import (
    HermesTransportError,
    LocalHermesConsoleTransport,
    RemoteHermesConsoleTransport,
    TransportBinding,
)
import remote_hermes
import server


SECRET = "inventory-secret-NEVER-RETURN"
ENDPOINT = "https://inventory.example"


def capability_payload(*, enabled=True, skills_path="/v1/skills", toolsets_path="/v1/toolsets"):
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
        "features": {"skills_api": enabled},
        "endpoints": {
            "health": {"method": "GET", "path": "/health"},
            "health_detailed": {"method": "GET", "path": "/health/detailed"},
            "skills": {"method": "GET", "path": skills_path},
            "toolsets": {"method": "GET", "path": toolsets_path},
        },
    }


def skills_payload(rows=None):
    return {
        "object": "list",
        "data": rows if rows is not None else [
            {
                "name": "github-workflow",
                "category": "development",
                "description": "Review repository work.",
                "path": f"/private/{SECRET}",
                "content": SECRET,
            },
            {
                "name": "calendar",
                "category": "productivity",
                "description": "Work with calendar events.",
            },
        ],
    }


def toolsets_payload(rows=None):
    return {
        "object": "list",
        "platform": "api_server",
        "data": rows if rows is not None else [
            {
                "name": "web",
                "label": "Web tools",
                "description": "Includes web_search and web_extract.",
                "enabled": False,
                "configured": True,
                "tools": ["web_search", "web_extract"],
            },
            {
                "name": "core",
                "label": "Core tools",
                "description": "Everyday agent tools.",
                "enabled": True,
                "configured": True,
                "tools": ["read_file"],
            },
        ],
    }


class FakeResponse:
    def __init__(self, status, payload, *, content_type="application/json"):
        self.status = status
        self.raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(self.raw)),
        }

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, amount):
        return self.raw[:amount]


class FakeConnection:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls
        self.closed = False

    def request(self, method, path, body=None, headers=None):
        self.calls.append({
            "method": method,
            "path": path,
            "body": body,
            "headers": dict(headers or {}),
        })

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class ResponseQueue:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.connections = []

    def __call__(self, _scheme, _host, _port, _timeout):
        connection = FakeConnection(self.responses.pop(0), self.calls)
        self.connections.append(connection)
        return connection


class FakeInventoryClient:
    def __init__(self, result=None):
        self.result = result or {
            "skills": [{"name": "calendar"}],
            "toolsets": [{"name": "core", "enabled": True, "tool_count": 4}],
            "skill_count": 1,
            "toolset_count": 1,
            "enabled_toolset_count": 1,
        }
        self.calls = 0

    def read_capability_inventory(self):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RemoteCapabilityInventoryTests(unittest.TestCase):
    def client(self, responses):
        queue = ResponseQueue([FakeResponse(*response) for response in responses])
        return remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=queue,
        ), queue

    def test_exact_advertised_authenticated_reads_return_allowlisted_bounded_metadata(self):
        client, queue = self.client([
            (200, capability_payload()),
            (200, skills_payload()),
            (200, toolsets_payload()),
        ])

        inventory = client.read_capability_inventory()

        self.assertEqual(
            [call["path"] for call in queue.calls],
            ["/v1/capabilities", "/v1/skills", "/v1/toolsets"],
        )
        self.assertTrue(all(call["method"] == "GET" for call in queue.calls))
        self.assertTrue(all(call["headers"]["Authorization"] == f"Bearer {SECRET}" for call in queue.calls))
        self.assertEqual(inventory["skill_count"], 2)
        self.assertEqual(inventory["enabled_toolset_count"], 1)
        self.assertEqual(
            [item["name"] for item in inventory["skills"]],
            ["calendar", "github-workflow"],
        )
        self.assertTrue(all("category" not in item for item in inventory["skills"]))
        self.assertTrue(all("description" not in item for item in inventory["skills"]))
        self.assertEqual(inventory["toolsets"][0]["name"], "core")
        self.assertNotIn("label", inventory["toolsets"][0])
        self.assertEqual(inventory["toolsets"][1]["tool_count"], 2)
        self.assertNotIn("description", inventory["toolsets"][1])
        serialized = json.dumps(inventory)
        for private in (SECRET, ENDPOINT, "path", "content", "configured", "web_search", "read_file"):
            self.assertNotIn(private, serialized)
        self.assertTrue(all(connection.closed for connection in queue.connections))

    def test_missing_capability_or_wrong_fixed_endpoint_fails_before_inventory_reads(self):
        cases = (
            (capability_payload(enabled=False), "remote_capability_inventory_unavailable"),
            (capability_payload(skills_path="/api/skills"), "remote_schema_unsupported"),
            (capability_payload(toolsets_path="/api/tools"), "remote_schema_unsupported"),
        )
        for capability, code in cases:
            with self.subTest(code=code, capability=capability):
                client, queue = self.client([(200, capability)])
                with self.assertRaisesRegex(remote_hermes.RemoteHermesError, code):
                    client.read_capability_inventory()
                self.assertEqual([call["path"] for call in queue.calls], ["/v1/capabilities"])

    def test_private_malformed_oversized_and_partial_responses_fail_closed(self):
        malformed_cases = (
            (
                skills_payload([{"name": SECRET, "category": "test", "description": "Ignored"}]),
                toolsets_payload([]),
                "remote_capability_inventory_private",
            ),
            (
                skills_payload([]),
                toolsets_payload([{"name": "core", "label": "Core", "description": "", "enabled": True, "tools": ["same", "same"]}]),
                "remote_capability_inventory_schema_invalid",
            ),
        )
        for skills, toolsets, code in malformed_cases:
            with self.subTest(code=code):
                client, _queue = self.client([
                    (200, capability_payload()),
                    (200, skills),
                    (200, toolsets),
                ])
                with self.assertRaisesRegex(remote_hermes.RemoteHermesError, code):
                    client.read_capability_inventory()

        oversized = [
            {"name": f"skill-{index}", "category": "test", "description": "Safe"}
            for index in range(remote_hermes.MAX_REMOTE_SKILLS + 1)
        ]
        client, _queue = self.client([
            (200, capability_payload()),
            (200, skills_payload(oversized)),
        ])
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_response_invalid"):
            client.read_capability_inventory()

        client, queue = self.client([
            (200, capability_payload()),
            (200, skills_payload([])),
            (500, {"error": {"message": SECRET}}),
        ])
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_unavailable"):
            client.read_capability_inventory()
        self.assertEqual([call["path"] for call in queue.calls], ["/v1/capabilities", "/v1/skills", "/v1/toolsets"])

    def test_multiline_descriptions_are_validated_but_never_exposed(self):
        client, _queue = self.client([
            (200, capability_payload()),
            (200, skills_payload([{
                "name": "computer-use",
                "category": "automation",
                "description": "Control a desktop safely.\nUse visible state before actions.\tUses web_search for inputs.",
            }])),
            (200, toolsets_payload([{
                "name": "web",
                "label": "Web tools",
                "description": "web_search, web_extract",
                "enabled": True,
                "configured": True,
                "tools": ["web_search", "web_extract"],
            }])),
        ])

        inventory = client.read_capability_inventory()

        self.assertNotIn("description", inventory["skills"][0])
        self.assertNotIn("description", inventory["toolsets"][0])
        self.assertNotIn("web_search", json.dumps(inventory))

    def test_path_like_ignored_metadata_stays_private(self):
        private_labels = (
            "source=/Users/alice/private/plan.md",
            "source=file:///Users/alice/private/plan.md",
            r"workspace=C:\Users\alice\private\plan.md",
            r"share=\\fileserver\private\plan.md",
            "source=//fileserver/private/plan.md",
            "source=./private/plan.md",
            "source=../private/plan.md",
            ".hermes/skills/foo/SKILL.md",
            r"skills\private\plan.md",
        )
        for label in private_labels:
            with self.subTest(label=label):
                client, _queue = self.client([
                    (200, capability_payload()),
                    (200, skills_payload([{
                        "name": "unsafe",
                        "category": label,
                        "description": "Not browser-visible.",
                    }])),
                    (200, toolsets_payload([])),
                ])
                inventory = client.read_capability_inventory()
                self.assertNotIn(label, json.dumps(inventory))

    def test_short_host_pagination_and_wrong_typed_metadata_fail_closed(self):
        for reflected_name in ("lab", "lab.internal", "lab-remote", "lab_remote"):
            with self.subTest(reflected_name=reflected_name):
                short_queue = ResponseQueue([
                    FakeResponse(200, capability_payload()),
                    FakeResponse(200, skills_payload([{
                        "name": reflected_name,
                        "category": "test",
                        "description": "Not browser-visible.",
                    }])),
                    FakeResponse(200, toolsets_payload([])),
                ])
                short_host_client = remote_hermes.RemoteHermesClient(
                    "https://lab",
                    SECRET,
                    connection_factory=short_queue,
                )
                with self.assertRaisesRegex(
                    remote_hermes.RemoteHermesError,
                    "remote_capability_inventory_private",
                ):
                    short_host_client.read_capability_inventory()

        allowed_queue = ResponseQueue([
            FakeResponse(200, capability_payload()),
            FakeResponse(200, skills_payload([{
                "name": "collaborative",
                "category": "test",
                "description": "Not browser-visible.",
            }])),
            FakeResponse(200, toolsets_payload([])),
        ])
        allowed_short_host = remote_hermes.RemoteHermesClient(
            "https://lab",
            SECRET,
            connection_factory=allowed_queue,
        )
        self.assertEqual(
            allowed_short_host.read_capability_inventory()["skills"][0]["name"],
            "collaborative",
        )

        malformed_envelopes = (
            ({**skills_payload([]), "has_more": True}, toolsets_payload([])),
            ({**skills_payload([]), "next_cursor": "secret"}, toolsets_payload([])),
            (skills_payload([]), {**toolsets_payload([]), "total": 100}),
            (skills_payload([{"name": "bad", "category": False, "description": "Safe"}]), toolsets_payload([])),
            (skills_payload([{"name": "bad", "category": "test", "description": 0}]), toolsets_payload([])),
            (skills_payload([]), toolsets_payload([{
                "name": "bad",
                "label": 0,
                "description": "Safe",
                "enabled": True,
                "tools": [],
            }])),
            (skills_payload([]), toolsets_payload([{
                "name": "vision",
                "label": "Vision / Image Analysis",
                "description": "Safe",
                "enabled": True,
                "tools": [],
            }])),
        )
        for skills, toolsets in malformed_envelopes[:-1]:
            with self.subTest(skills=skills, toolsets=toolsets):
                client, _queue = self.client([
                    (200, capability_payload()),
                    (200, skills),
                    (200, toolsets),
                ])
                with self.assertRaisesRegex(
                    remote_hermes.RemoteHermesError,
                    "remote_capability_inventory_schema_invalid",
                ):
                    client.read_capability_inventory()

        compatible_skills, compatible_toolsets = malformed_envelopes[-1]
        compatible_client, _queue = self.client([
            (200, capability_payload()),
            (200, compatible_skills),
            (200, compatible_toolsets),
        ])
        compatible_inventory = compatible_client.read_capability_inventory()
        self.assertEqual(compatible_inventory["toolsets"][0]["name"], "vision")
        self.assertNotIn("label", compatible_inventory["toolsets"][0])

    def test_invalid_optional_inventory_contract_does_not_disable_runs_or_sessions(self):
        capabilities = capability_payload(skills_path="/future/skills")
        capabilities["features"].update({
            "run_submission": True,
            "run_status": True,
            "run_events_sse": True,
            "run_stop": True,
            "session_resources": True,
        })
        capabilities["endpoints"].update({
            "runs": {"method": "POST", "path": "/v1/runs"},
            "run_status": {"method": "GET", "path": "/v1/runs/{run_id}"},
            "run_events": {"method": "GET", "path": "/v1/runs/{run_id}/events"},
            "run_stop": {"method": "POST", "path": "/v1/runs/{run_id}/stop"},
            "sessions": {"method": "GET", "path": "/api/sessions"},
            "session": {"method": "GET", "path": "/api/sessions/{session_id}"},
            "session_messages": {"method": "GET", "path": "/api/sessions/{session_id}/messages"},
        })
        health = {
            "status": "ok",
            "platform": "hermes-agent",
            "version": "0.18.2",
            "readiness": {"status": "ok", "checks": {"config": {"status": "ok"}}},
        }
        discovery_responses = [
            (200, {"status": "ok"}),
            (200, health),
            (200, capabilities),
        ]
        run_client, _run_queue = self.client(discovery_responses)
        session_client, _session_queue = self.client(discovery_responses)
        inventory_client, _inventory_queue = self.client([(200, capabilities)])

        self.assertIn("run_submission", run_client.require_console_run_capabilities()["capabilities"])
        self.assertIn("session_resources", session_client.require_session_resource_capabilities()["capabilities"])
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_schema_unsupported"):
            inventory_client.read_capability_inventory()

    def test_server_payload_is_binding_safe_all_or_nothing_and_local_is_network_free(self):
        local = LocalHermesConsoleTransport(
            TransportBinding("local", "Local Hermes", "local-default"),
            command_path=None,
            hermes_home=Path("/not-read"),
            cwd=Path("/not-read"),
        )
        with patch.object(server, "hermes_console_transport", return_value=local):
            payload = server.hermes_capability_inventory_payload()
        self.assertEqual(payload["status"], "local")
        self.assertEqual(payload["skills"], [])
        self.assertNotIn(SECRET, json.dumps(payload))

        client = FakeInventoryClient()
        remote = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Workshop Hermes", "b" * 32),
            client=client,
        )
        with patch.object(remote, "revalidate") as revalidate, patch.object(
            server,
            "hermes_console_transport",
            return_value=remote,
        ):
            payload = server.hermes_capability_inventory_payload()
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["summary"]["skill_count"], 1)
        self.assertEqual(client.calls, 1)
        self.assertEqual(revalidate.call_count, 2)

        with patch.object(
            remote,
            "revalidate",
            side_effect=[None, HermesTransportError("transport_binding_changed")],
        ), patch.object(server, "hermes_console_transport", return_value=remote):
            changed = server.hermes_capability_inventory_payload()
        self.assertEqual(changed["status"], "unavailable")
        self.assertEqual(changed["skills"], [])
        self.assertEqual(changed["toolsets"], [])

    def test_server_route_and_unsupported_state_are_public_safe(self):
        remote = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Workshop Hermes", "c" * 32),
            client=FakeInventoryClient(
                remote_hermes.RemoteHermesError("remote_capability_inventory_unavailable")
            ),
        )
        with patch.object(remote, "revalidate"), patch.object(
            server,
            "hermes_console_transport",
            return_value=remote,
        ):
            payload = server.hermes_capability_inventory_payload()
        self.assertEqual(payload["status"], "unsupported")
        self.assertNotIn(SECRET, json.dumps(payload))
        self.assertIs(server.API_ROUTES["/api/hermes/capabilities"], server.hermes_capability_inventory_payload)


if __name__ == "__main__":
    unittest.main()
