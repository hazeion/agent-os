from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hermes_transport import HermesTransportError
import remote_hermes
import server


SECRET = "cron-inventory-secret-NEVER-RETURN"
ENDPOINT = "https://cron-inventory.example"
JOBS_PATH = "/v1/jobs"


def capability_payload(
    *,
    enabled: bool = True,
    path: str = JOBS_PATH,
    version: int = 1,
) -> dict:
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
        "features": {
            "jobs_inventory": enabled,
            "jobs_inventory_version": version,
            "jobs_inventory_complete": True,
            "jobs_inventory_requires_api_key": True,
            "jobs_inventory_read_only": True,
            "jobs_inventory_max_jobs": 128,
            "jobs_inventory_max_response_bytes": 256 * 1024,
        },
        "endpoints": {
            "health": {"method": "GET", "path": "/health"},
            "health_detailed": {"method": "GET", "path": "/health/detailed"},
            "jobs_inventory": {"method": "GET", "path": path, "version": version},
        },
    }


def remote_job(**overrides) -> dict:
    job = {
        "id": "aabbccddeeff",
        "name": "Cron job aabbccddeeff",
        "schedule": "0 9 * * *",
        "enabled": True,
        "last_run": "2026-07-28T09:00:00+00:00",
        "next_run": "2026-07-29T09:00:00+00:00",
        "last_status": "completed",
        "configuration_revision": "a" * 64,
    }
    job.update(overrides)
    return job


class FakeResponse:
    def __init__(self, status: int, payload, *, content_type: str = "application/json"):
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

    def __call__(self, _scheme, _host, _port, _timeout):
        connection = FakeConnection(self.responses.pop(0), self.calls)
        self.connections.append(connection)
        return connection


class FakeCronTransport:
    mode = "remote"

    def __init__(self, result):
        self.result = result
        self.binding = SimpleNamespace(label="Remote Hermes")
        self.revalidations = 0
        self.reads = 0

    def revalidate(self, _data_root):
        self.revalidations += 1

    def read_cron_jobs(self):
        self.reads += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RemoteCronInventoryTests(unittest.TestCase):
    def client(self, responses):
        queue = ResponseQueue([FakeResponse(*response) for response in responses])
        return remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=queue,
        ), queue

    def test_exact_advertised_authenticated_read_returns_only_public_job_fields(self):
        client, queue = self.client(
            [
                (200, capability_payload()),
                (
                    200,
                    {
                        "object": "hermes.jobs.inventory",
                        "version": 1,
                        "count": 2,
                        "enabled_count": 1,
                        "jobs": [
                            remote_job(),
                            remote_job(
                                id="112233445566",
                                name="Cron job 112233445566",
                                enabled=False,
                                last_run=None,
                                next_run=None,
                                last_status="paused",
                                configuration_revision="b" * 64,
                            ),
                        ]
                    },
                ),
            ]
        )

        inventory = client.read_cron_jobs()

        self.assertEqual(
            [call["path"] for call in queue.calls],
            ["/v1/capabilities", JOBS_PATH],
        )
        self.assertTrue(all(call["method"] == "GET" for call in queue.calls))
        self.assertTrue(
            all(
                call["headers"]["Authorization"] == f"Bearer {SECRET}"
                for call in queue.calls
            )
        )
        self.assertEqual(inventory["count"], 2)
        self.assertEqual(inventory["enabled_count"], 1)
        self.assertEqual(
            set(inventory["jobs"][0]),
            {
                "id",
                "name",
                "schedule",
                "enabled",
                "last_run",
                "next_run",
                "last_status",
                "configuration_revision",
            },
        )
        self.assertEqual(inventory["jobs"][0]["last_status"], "completed")
        self.assertEqual(inventory["jobs"][0]["schedule"], "0 9 * * *")
        self.assertEqual(inventory["jobs"][1]["last_status"], "paused")
        serialized = json.dumps(inventory)
        for private in (
            SECRET,
            ENDPOINT,
            "prompt",
            "deliver",
            "origin",
        ):
            self.assertNotIn(private, serialized)
        self.assertTrue(all(connection.closed for connection in queue.connections))

    def test_missing_or_wrong_capability_fails_before_jobs_read(self):
        cases = (
            (
                capability_payload(enabled=False),
                "remote_cron_inventory_unavailable",
            ),
            (
                capability_payload(path="/api/jobs"),
                "remote_schema_unsupported",
            ),
            (
                capability_payload(version=2),
                "remote_schema_unsupported",
            ),
            (
                capability_payload(version=True),
                "remote_schema_unsupported",
            ),
        )
        for capability, code in cases:
            with self.subTest(code=code, capability=capability):
                client, queue = self.client([(200, capability)])
                with self.assertRaisesRegex(remote_hermes.RemoteHermesError, code):
                    client.read_cron_jobs()
                self.assertEqual(
                    [call["path"] for call in queue.calls],
                    ["/v1/capabilities"],
                )

    def test_malformed_optional_jobs_contract_does_not_break_capability_discovery(self):
        client, queue = self.client([(200, capability_payload(version=True))])

        capabilities = client._trusted_capabilities()

        self.assertIn("jobs_inventory", capabilities["features"])
        self.assertFalse(capabilities["cron_inventory_contract_valid"])
        self.assertEqual(
            [call["path"] for call in queue.calls],
            ["/v1/capabilities"],
        )

    def test_malformed_duplicate_private_and_excessive_jobs_fail_closed(self):
        def envelope(jobs, *, count=None, enabled_count=None):
            return {
                "object": "hermes.jobs.inventory",
                "version": 1,
                "count": len(jobs) if count is None else count,
                "enabled_count": (
                    sum(1 for job in jobs if job.get("enabled") is True)
                    if enabled_count is None
                    else enabled_count
                ),
                "jobs": jobs,
            }

        cases = (
            (
                envelope([remote_job(id="not/a/safe/id")]),
                "remote_cron_inventory_schema_invalid",
            ),
            (
                envelope(
                    [
                        remote_job(),
                        remote_job(),
                    ]
                ),
                "remote_cron_inventory_schema_invalid",
            ),
            (
                envelope([remote_job(name=f"Cron job {SECRET}")]),
                "remote_cron_inventory_(?:private|schema_invalid)",
            ),
            (
                envelope([remote_job(name="AKIAABCDEFGHIJKLMNOP")]),
                "remote_cron_inventory_(?:private|schema_invalid)",
            ),
            (
                envelope([remote_job(schedule="1")]),
                "remote_cron_inventory_schema_invalid",
            ),
            (
                envelope([remote_job(last_status="private status prose")]),
                "remote_cron_inventory_schema_invalid",
            ),
            (
                envelope([remote_job(next_run="tomorrow morning")]),
                "remote_cron_inventory_schema_invalid",
            ),
            (
                envelope(
                    [
                        {
                            "id": f"{index:012x}",
                            "name": "Bounded job",
                            "schedule": "0 9 * * *",
                            "enabled": True,
                            "last_run": None,
                            "next_run": None,
                            "last_status": "scheduled",
                            "configuration_revision": f"{index:064x}",
                        }
                        for index in range(remote_hermes.MAX_REMOTE_CRON_JOBS + 1)
                    ]
                ),
                "remote_response_invalid",
            ),
            (
                envelope(
                    [
                        {
                            **remote_job(),
                            "prompt": "This field is never part of the public contract.",
                        }
                    ]
                ),
                "remote_cron_inventory_schema_invalid",
            ),
            (
                envelope([remote_job()], count=2),
                "remote_cron_inventory_schema_invalid",
            ),
            (
                envelope([remote_job(configuration_revision="not-a-revision")]),
                "remote_cron_inventory_schema_invalid",
            ),
            (
                {
                    **envelope([remote_job()]),
                    "version": True,
                },
                "remote_cron_inventory_schema_invalid",
            ),
        )
        for jobs_payload, code in cases:
            with self.subTest(code=code):
                client, _queue = self.client(
                    [
                        (200, capability_payload()),
                        (200, jobs_payload),
                    ]
                )
                with self.assertRaisesRegex(remote_hermes.RemoteHermesError, code):
                    client.read_cron_jobs()

    def test_selected_remote_payload_is_binding_safe_and_generic_on_failure(self):
        transport = FakeCronTransport(
            {
                "count": 1,
                "enabled_count": 1,
                "jobs": [
                    {
                        "id": "aabbccddeeff",
                        "name": "Cron job aabbccddeeff",
                        "schedule": "0 9 * * *",
                        "enabled": True,
                        "last_run": None,
                        "next_run": "2026-07-29T09:00:00+00:00",
                        "last_status": "scheduled",
                        "configuration_revision": "a" * 64,
                    }
                ],
            }
        )
        with patch.object(server, "hermes_console_transport", return_value=transport):
            payload = server.selected_cron_jobs()

        self.assertEqual(payload["mode"], "remote")
        self.assertEqual(payload["source"], "remote")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(transport.revalidations, 2)
        self.assertEqual(transport.reads, 1)

        rejected = FakeCronTransport(
            HermesTransportError("remote_cron_inventory_schema_invalid")
        )
        with patch.object(server, "hermes_console_transport", return_value=rejected):
            unavailable = server.selected_cron_jobs()

        self.assertEqual(unavailable["jobs"], [])
        self.assertEqual(unavailable["count"], 0)
        self.assertEqual(unavailable["status"], "unavailable")
        self.assertNotIn("schema", unavailable["error"].lower())
        self.assertNotIn(SECRET, json.dumps(unavailable))

    def test_local_selection_stays_network_free_and_overview_uses_selected_inventory(self):
        local = SimpleNamespace(mode="local")
        local_payload = {
            "exists": True,
            "source": "local-fixture",
            "count": 2,
            "enabled_count": 1,
            "jobs": [],
        }
        with patch.object(server, "hermes_console_transport", return_value=local), patch.object(
            server, "read_cron_jobs", return_value=local_payload
        ) as local_read:
            selected = server.selected_cron_jobs()
        self.assertEqual(selected, local_payload)
        local_read.assert_called_once_with()

        with patch.object(
            server,
            "selected_cron_jobs",
            return_value={"count": 4, "enabled_count": 3, "jobs": []},
        ), patch.object(
            server, "read_cron_jobs", side_effect=AssertionError("local cron read")
        ), patch.object(
            server, "read_json_file", return_value=[]
        ), patch.object(
            server, "sessions_payload", return_value={"sessions": []}
        ):
            payload = server.overview()
        self.assertEqual(payload["cards"]["scheduled_crons"], 4)


if __name__ == "__main__":
    unittest.main()
