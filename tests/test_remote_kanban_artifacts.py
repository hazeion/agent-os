import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from delegation_artifacts import (
    binding_ids,
    import_remote_task_artifacts,
    list_task_artifacts,
    reconcile_task_artifact_bindings,
    remove_task_artifacts,
)
from hermes_kanban import RemoteHermesKanbanAdapter
from mentat_db import connect
from remote_hermes import RemoteHermesClient, RemoteHermesError
import server


def artifact(content=b"# Result\n", **updates):
    payload = {
        "id": "hart_" + "a" * 64,
        "object": "hermes.kanban.artifact",
        "name": "result.md",
        "kind": "text",
        "mime_type": "text/markdown",
        "byte_size": len(content),
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        "created_at": 1785348000,
    }
    payload.update(updates)
    return payload


class FakeResponse:
    def __init__(self, status, content, headers=None):
        self.status = status
        self.content = content
        self.offset = 0
        self.headers = dict(headers or {})

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, amount):
        chunk = self.content[self.offset : self.offset + amount]
        self.offset += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.closed = False

    def request(self, method, path, headers=None):
        self.calls.append((method, path, dict(headers or {})))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class RemoteClientArtifactTests(unittest.TestCase):
    def client(self):
        client = RemoteHermesClient("https://hermes.example", "private-test-key")
        client.require_kanban_artifact_capabilities = lambda: {
            "features": [
                "kanban_api",
                "kanban_api_requires_api_key",
                "kanban_artifacts",
                "kanban_artifacts_requires_api_key",
                "kanban_artifacts_digests",
            ]
        }
        return client

    def test_manifest_is_exact_bounded_and_path_free(self):
        item = artifact()
        payload = {
            "object": "hermes.kanban.artifact_list",
            "version": 1,
            "complete": True,
            "task_id": "t_12345678",
            "data": [item],
            "rejected_count": 1,
            "total_bytes": item["byte_size"],
        }
        client = self.client()
        client._contract_json_request = lambda method, path: payload
        result = client.list_kanban_artifacts("default", "t_12345678")
        self.assertEqual(result["artifacts"][0]["name"], "result.md")
        self.assertNotIn("path", result["artifacts"][0])
        self.assertEqual(result["rejected_count"], 1)

    def test_capability_contract_is_optional_but_exact_when_advertised(self):
        client = RemoteHermesClient("https://hermes.example", "private-test-key")
        base = {
            "object": "hermes.api_server.capabilities",
            "platform": "hermes-agent",
            "model": "anthropic/test-model",
            "auth": {"type": "bearer", "required": True},
            "runtime": {
                "mode": "server_agent",
                "tool_execution": "server",
                "split_runtime": False,
            },
            "features": {
                "kanban_api": True,
                "kanban_api_version": 1,
                "kanban_api_revisioned": True,
                "kanban_api_idempotency": True,
                "kanban_api_requires_api_key": True,
            },
            "endpoints": {
                "health": {"method": "GET", "path": "/health"},
                "health_detailed": {
                    "method": "GET",
                    "path": "/health/detailed",
                },
                "kanban_boards": {
                    "method": "GET",
                    "path": "/v1/kanban/boards",
                },
                "kanban_profiles": {
                    "method": "GET",
                    "path": "/v1/kanban/profiles?board={board}",
                },
                "kanban_tasks": {
                    "method": "GET",
                    "path": "/v1/kanban/tasks?board={board}",
                },
                "kanban_task": {
                    "method": "GET",
                    "path": "/v1/kanban/tasks/{task_id}?board={board}",
                },
                "kanban_task_create": {
                    "method": "POST",
                    "path": "/v1/kanban/tasks?board={board}",
                },
                "kanban_task_action": {
                    "method": "POST",
                    "path": "/v1/kanban/tasks/{task_id}/actions?board={board}",
                },
            },
        }
        client._request_json = lambda *args, **kwargs: base
        self.assertNotIn(
            "kanban_artifacts",
            client._trusted_capabilities()["features"],
        )

        advertised = {
            **base,
            "features": {
                **base["features"],
                "kanban_artifacts": True,
                "kanban_artifacts_version": 1,
                "kanban_artifacts_requires_api_key": True,
                "kanban_artifacts_digests": True,
                "kanban_artifacts_max_files": 10,
                "kanban_artifacts_max_bytes": 100 * 1024 * 1024,
                "kanban_artifacts_max_total_bytes": 250 * 1024 * 1024,
            },
            "endpoints": {
                **base["endpoints"],
                "kanban_task_artifacts": {
                    "method": "GET",
                    "path": "/v1/kanban/tasks/{task_id}/artifacts?board={board}",
                },
                "kanban_task_artifact": {
                    "method": "GET",
                    "path": "/v1/kanban/tasks/{task_id}/artifacts/{artifact_id}?board={board}",
                },
            },
        }
        client._request_json = lambda *args, **kwargs: advertised
        self.assertIn(
            "kanban_artifacts",
            client._trusted_capabilities()["features"],
        )
        advertised["features"]["kanban_artifacts_max_files"] = 11
        with self.assertRaises(RemoteHermesError):
            client._trusted_capabilities()

    def test_manifest_rejects_unsupported_and_secret_shaped_files(self):
        for unsafe in (
            artifact(name="page.html", mime_type="text/html"),
            artifact(name="api-token.md"),
            artifact(name="../result.md"),
        ):
            client = self.client()
            client._contract_json_request = lambda method, path, item=unsafe: {
                "object": "hermes.kanban.artifact_list",
                "version": 1,
                "complete": True,
                "task_id": "t_12345678",
                "data": [item],
                "rejected_count": 0,
                "total_bytes": item["byte_size"],
            }
            with self.assertRaises(RemoteHermesError):
                client.list_kanban_artifacts("default", "t_12345678")

    def test_download_binds_auth_and_verifies_digest(self):
        content = b"# Result\n"
        item = artifact(content)
        response = FakeResponse(
            200,
            content,
            {
                "Content-Type": item["mime_type"],
                "Content-Length": str(len(content)),
                "X-Hermes-Artifact-Id": item["id"],
                "X-Hermes-Artifact-Digest": item["digest"],
            },
        )
        connection = FakeConnection(response)
        client = self.client()
        client._connection = lambda **_kwargs: connection
        self.assertEqual(
            client.download_kanban_artifact(
                "default",
                "t_12345678",
                item,
            ),
            content,
        )
        _, path, headers = connection.calls[0]
        self.assertEqual(
            path,
            f"/v1/kanban/tasks/t_12345678/artifacts/{item['id']}?board=default",
        )
        self.assertEqual(headers["Authorization"], "Bearer private-test-key")
        self.assertTrue(connection.closed)

    def test_download_rejects_redirect_and_digest_mismatch(self):
        item = artifact()
        for response in (
            FakeResponse(302, b"", {"Location": "https://other.example/file"}),
            FakeResponse(
                200,
                b"changed",
                {
                    "Content-Type": item["mime_type"],
                    "Content-Length": str(len(b"changed")),
                    "X-Hermes-Artifact-Id": item["id"],
                    "X-Hermes-Artifact-Digest": item["digest"],
                },
            ),
        ):
            client = self.client()
            client._connection = lambda response=response, **_kwargs: FakeConnection(response)
            with self.assertRaises(RemoteHermesError):
                client.download_kanban_artifact(
                    "default",
                    "t_12345678",
                    item,
                )


class AdapterClient:
    def __init__(self, content=b"# Result\n"):
        self.content = content
        self.download_calls = 0

    def list_kanban_artifacts(self, board, task_id):
        return {
            "task_id": task_id,
            "artifacts": [artifact(self.content)],
            "rejected_count": 0,
            "total_bytes": len(self.content),
        }

    def download_kanban_artifact(self, board, task_id, metadata):
        return self.content

    def stream_kanban_artifact(self, board, task_id, metadata, destination):
        self.download_calls += 1
        destination.write(self.content)
        return len(self.content)


class PrivateArtifactSnapshotTests(unittest.TestCase):
    def test_verified_file_is_snapshotted_and_removed_with_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            adapter = RemoteHermesKanbanAdapter(
                AdapterClient(),
                connection_binding_id="b" * 32,
            )
            result = import_remote_task_artifacts(
                data_dir,
                mentat_task_id="task_local",
                connection_binding_id="b" * 32,
                board="default",
                remote_task_id="t_12345678",
                adapter=adapter,
            )
            self.assertEqual(result["state"], "synced")
            stored = list_task_artifacts(
                data_dir,
                "task_local",
                connection_binding_id="b" * 32,
                board="default",
                remote_task_id="t_12345678",
            )
            self.assertEqual(len(stored), 1)
            self.assertRegex(stored[0]["id"], r"attachment_[0-9a-f]{32}")
            self.assertEqual(len(binding_ids(data_dir)), 1)
            self.assertEqual(remove_task_artifacts(data_dir, "task_local"), 1)
            self.assertEqual(list_task_artifacts(data_dir, "task_local"), [])
            self.assertEqual(binding_ids(data_dir), ())

    def test_same_remote_id_cannot_cross_connection_or_board(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            for connection_binding_id, board in (
                ("b" * 32, "default"),
                ("c" * 32, "other"),
            ):
                import_remote_task_artifacts(
                    data_dir,
                    mentat_task_id="task_local",
                    connection_binding_id=connection_binding_id,
                    board=board,
                    remote_task_id="t_12345678",
                    adapter=RemoteHermesKanbanAdapter(
                        AdapterClient(
                            f"# {connection_binding_id[0]}\n".encode()
                        ),
                        connection_binding_id=connection_binding_id,
                    ),
                )
            first = list_task_artifacts(
                data_dir,
                "task_local",
                connection_binding_id="b" * 32,
                board="default",
                remote_task_id="t_12345678",
            )
            second = list_task_artifacts(
                data_dir,
                "task_local",
                connection_binding_id="c" * 32,
                board="other",
                remote_task_id="t_12345678",
            )
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertNotEqual(first[0]["id"], second[0]["id"])

    def test_startup_reconciliation_drops_deleted_task_bindings(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            import_remote_task_artifacts(
                data_dir,
                mentat_task_id="task_local",
                connection_binding_id="b" * 32,
                board="default",
                remote_task_id="t_12345678",
                adapter=RemoteHermesKanbanAdapter(
                    AdapterClient(),
                    connection_binding_id="b" * 32,
                ),
            )
            self.assertEqual(len(binding_ids(data_dir)), 1)
            self.assertEqual(
                reconcile_task_artifact_bindings(data_dir, []),
                (),
            )
            self.assertEqual(list_task_artifacts(data_dir, "task_local"), [])

    def test_secret_content_is_never_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            adapter = RemoteHermesKanbanAdapter(
                AdapterClient(b"api_key=abcdefghijklmnop123456"),
                connection_binding_id="b" * 32,
            )
            result = import_remote_task_artifacts(
                data_dir,
                mentat_task_id="task_local",
                connection_binding_id="b" * 32,
                board="default",
                remote_task_id="t_12345678",
                adapter=adapter,
            )
            self.assertEqual(result["state"], "partial")
            self.assertEqual(result["accepted_count"], 0)
            self.assertEqual(
                list_task_artifacts(
                    data_dir,
                    "task_local",
                    connection_binding_id="b" * 32,
                    board="default",
                    remote_task_id="t_12345678",
                ),
                [],
            )

    def test_tasks_api_decorates_private_files_without_changing_tracked_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            tasks_path = data_dir / "tasks.json"
            tasks_path.write_text(
                '[{"id":"task_local","title":"Review","delegation":'
                '{"connection_binding_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
                '"board_id":"default","kanban_task_id":"t_12345678"}}]',
                encoding="utf-8",
            )
            import_remote_task_artifacts(
                data_dir,
                mentat_task_id="task_local",
                connection_binding_id="b" * 32,
                board="default",
                remote_task_id="t_12345678",
                adapter=RemoteHermesKanbanAdapter(
                    AdapterClient(),
                    connection_binding_id="b" * 32,
                ),
            )
            before = tasks_path.read_bytes()
            with (
                patch.object(server, "DATA_DIR", data_dir),
                patch.object(server, "CONFIGURED_DATA_DIR", data_dir),
            ):
                payload = server.tasks_payload()
            self.assertEqual(tasks_path.read_bytes(), before)
            public = payload["tasks"][0]["delegation"]["artifacts"][0]
            self.assertEqual(
                public["content_url"],
                f"/api/agent-console/attachments/{public['id']}/content",
            )
            self.assertNotIn("digest", public)
            self.assertNotIn("path", public)
            self.assertNotIn("hart_", str(payload))

    def test_missing_private_blob_is_unavailable_and_downloaded_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            data_dir.mkdir()
            tasks_path = data_dir / "tasks.json"
            tasks_path.write_text(
                '[{"id":"task_local","title":"Review","delegation":'
                '{"connection_binding_id":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
                '"board_id":"default","kanban_task_id":"t_12345678"}}]',
                encoding="utf-8",
            )
            client = AdapterClient()
            adapter = RemoteHermesKanbanAdapter(
                client,
                connection_binding_id="b" * 32,
            )
            import_remote_task_artifacts(
                data_dir,
                mentat_task_id="task_local",
                connection_binding_id="b" * 32,
                board="default",
                remote_task_id="t_12345678",
                adapter=adapter,
            )
            connection = connect(data_dir)
            try:
                connection.execute("UPDATE blobs SET state = 'missing'")
            finally:
                connection.close()
            with (
                patch.object(server, "DATA_DIR", data_dir),
                patch.object(server, "CONFIGURED_DATA_DIR", data_dir),
            ):
                public = server.tasks_payload()["tasks"][0]["delegation"]["artifacts"]
            self.assertEqual(len(public), 1)
            self.assertNotIn("content_url", public[0])
            self.assertEqual(public[0]["name"], "result.md")

            result = import_remote_task_artifacts(
                data_dir,
                mentat_task_id="task_local",
                connection_binding_id="b" * 32,
                board="default",
                remote_task_id="t_12345678",
                adapter=adapter,
            )
            self.assertEqual(result["state"], "synced")
            self.assertEqual(client.download_calls, 2)
            self.assertEqual(
                len(
                    list_task_artifacts(
                        data_dir,
                        "task_local",
                        connection_binding_id="b" * 32,
                        board="default",
                        remote_task_id="t_12345678",
                    )
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
