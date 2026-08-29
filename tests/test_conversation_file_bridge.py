from __future__ import annotations

from contextlib import closing
from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote

from mentat import local_bridge
from agent_registry import AgentRegistry
from agent_runtime import RuntimeContext
from agent_console_attachments import AttachmentUnavailable, create_attachment
from agent_console_attachments import resolve_blob_path
from conversation_repository import ConversationRepository
from conversation_attachments import staged_context_evidence
from mentat_db import connect
import server


TOKEN = "bridge-token-that-is-long-enough-for-256-bits-of-entropy"
CONVERSATION_ID = "conv_" + "a" * 32
ATTACHMENT_ID = "attachment_" + "b" * 32
PACK_ID = "pack_" + "c" * 16
PACK_REVISION = "sha256:" + "d" * 64
TEST_AGENT_ID = "agent_conversation_files"


def conversation_repository_with_test_agent(root: Path) -> ConversationRepository:
    AgentRegistry(root, supported_runtime_types=("hermes",)).create_agent(
        agent_id=TEST_AGENT_ID,
        name="Conversation files",
        runtime_config_id="runtime_conversation_files",
        runtime_type="hermes",
        runtime_agent_ref="conversation-files",
        capabilities=("run.message", "run.start"),
    )
    return ConversationRepository(root, supported_runtime_types=("hermes",))


def staged_payload(*, source: str = "upload") -> dict[str, object]:
    return {
        "schema_version": 1,
        "conversation_id": CONVERSATION_ID,
        "attachments": [{
            "id": ATTACHMENT_ID,
            "name": "notes.md",
            "mime_type": "text/markdown",
            "kind": "text",
            "byte_size": 5,
            "state": "staged",
            "available": True,
            "created_at": "2026-08-29T12:00:00Z",
            "expires_at": "2026-08-29T14:00:00Z",
            "source": source,
            "ordinal": 0,
        }],
        "context_pack": None,
        "limits": {"direct": 5, "total": 8, "images": 1},
    }


def media_item() -> dict[str, object]:
    staged = staged_payload()["attachments"][0]
    return {
        key: value
        for key, value in staged.items()
        if key not in {"source", "ordinal"}
    }


class ConversationFileBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = local_bridge.build_bridge_server("127.0.0.1", 0, TOKEN)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        request_headers = {
            "Host": f"127.0.0.1:{self.port}",
            local_bridge.BRIDGE_TOKEN_HEADER: TOKEN,
        }
        request_headers.update(headers or {})
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            return (
                response.status,
                content,
                {name: value for name, value in response.getheaders()},
            )
        finally:
            connection.close()

    def json_request(self, *args, **kwargs) -> tuple[int, dict, dict[str, str]]:
        status, body, headers = self.request(*args, **kwargs)
        return status, json.loads(body), headers

    def test_raw_upload_uses_one_exact_bounded_body_and_canonical_filename(self):
        captured: dict[str, object] = {}

        def stage(conversation_id, *, original_name, content_type, content):
            captured.update({
                "conversation_id": conversation_id,
                "original_name": original_name,
                "content_type": content_type,
                "content": content,
            })
            return {
                **staged_payload(),
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
            }, 201

        filename = "research notes.md"
        with patch.object(local_bridge, "bridge_stage_conversation_upload", side_effect=stage):
            status, payload, _headers = self.json_request(
                "POST",
                f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments",
                body=b"hello",
                headers={
                    "Content-Type": "text/markdown",
                    "Content-Length": "5",
                    local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: quote(
                        filename, safe="-_.!~*'()"
                    ),
                },
            )

        self.assertEqual(status, 201)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(captured, {
            "conversation_id": CONVERSATION_ID,
            "original_name": filename,
            "content_type": "text/markdown",
            "content": b"hello",
        })
        self.assertNotIn("path", json.dumps(payload))
        self.assertNotIn("sha256", json.dumps(payload))

    def test_raw_upload_rejects_noncanonical_metadata_and_transfer_encoding(self):
        cases = (
            ({
                "Content-Type": "text/markdown; charset=utf-8",
                "Content-Length": "5",
                local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: "notes.md",
            }, 415),
            ({
                "Content-Type": "text/markdown",
                "Content-Length": "5",
                local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: "notes%2emd",
            }, 404),
            ({
                "Content-Type": "text/markdown",
                "Content-Length": "5",
                "Transfer-Encoding": "chunked",
                local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: "notes.md",
            }, 404),
            ({
                "Content-Type": "text/markdown",
                "Content-Length": "5",
                "Content-Range": "bytes 0-4/5",
                local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: "notes.md",
            }, 404),
        )
        for headers, expected_status in cases:
            with self.subTest(headers=headers):
                status, payload, _response_headers = self.json_request(
                    "POST",
                    f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments",
                    body=b"hello",
                    headers=headers,
                )
                self.assertEqual(status, expected_status)
                if expected_status == 404:
                    self.assertEqual(payload, {"error": "bridge_route_not_found"})
                else:
                    self.assertEqual(payload["status"], "unsupported")

        status, payload, _headers = self.json_request(
            "POST",
            f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments",
            body=b"x",
            headers={
                "Content-Type": "text/markdown",
                "Content-Length": str(local_bridge.MAXIMUM_BRIDGE_UPLOAD_BODY_BYTES + 1),
                local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: "notes.md",
            },
        )
        self.assertEqual(status, 413)
        self.assertEqual(payload["status"], "too_large")

        status, payload, _headers = self.json_request(
            "POST",
            f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments",
            body=b"x",
            headers={
                "Content-Type": "application/pdf",
                "Content-Length": "1",
                local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: "notes.pdf",
            },
        )
        self.assertEqual(status, 415)
        self.assertEqual(payload["status"], "unsupported")

    def test_staged_workspace_context_pack_and_media_routes_are_fixed(self):
        workspace = {
            "schema_version": 1,
            "query": "readme",
            "files": [{
                "root_id": "workspace",
                "path": "README.md",
                "name": "README.md",
                "kind": "text",
                "mime_type": "text/markdown",
                "byte_size": 100,
            }],
        }
        packs = {
            "schema_version": 1,
            "context_packs": [{
                "id": PACK_ID,
                "name": "Delivery",
                "description": "Reviewed files",
                "revision": PACK_REVISION,
                "item_count": 1,
            }],
            "max_items": 8,
        }
        media = {
            "schema_version": 1,
            "conversation_id": CONVERSATION_ID,
            "runs": [{
                "run_id": "run_" + "e" * 32,
                "created_at": "2026-08-29T12:00:00Z",
                "inputs": [media_item()],
                "outputs": [],
            }],
        }
        routes = (
            (
                f"/bridge/v1/conversations/{CONVERSATION_ID}/staged-context",
                "bridge_conversation_staged_context_payload",
                (staged_payload(), 200),
            ),
            (
                "/bridge/v1/workspace-files?query=readme",
                "bridge_workspace_files_payload",
                (workspace, 200),
            ),
            (
                "/bridge/v1/context-packs",
                "bridge_context_pack_summaries_payload",
                (packs, 200),
            ),
            (
                f"/bridge/v1/conversations/{CONVERSATION_ID}/media",
                "bridge_conversation_media_payload",
                (media, 200),
            ),
        )
        for path, method, result in routes:
            with self.subTest(path=path), patch.object(
                local_bridge, method, return_value=result
            ):
                status, payload, _headers = self.json_request("GET", path)
                self.assertEqual(status, 200)
                self.assertEqual(payload["schema_version"], 1)

        status, payload, _headers = self.json_request(
            "GET", "/bridge/v1/workspace-files?root=/private"
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "bridge_route_not_found"})

    def test_release_workspace_and_context_pack_mutations_accept_only_exact_json(self):
        routes = (
            (
                f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments/{ATTACHMENT_ID}/release",
                "bridge_release_conversation_attachment",
                {},
            ),
            (
                f"/bridge/v1/conversations/{CONVERSATION_ID}/workspace-files",
                "bridge_stage_workspace_file",
                {"root_id": "workspace", "relative_path": "README.md"},
            ),
            (
                f"/bridge/v1/conversations/{CONVERSATION_ID}/context-packs/{PACK_ID}",
                "bridge_apply_conversation_context_pack",
                {"expected_revision": PACK_REVISION},
            ),
            (
                f"/bridge/v1/conversations/{CONVERSATION_ID}/context-packs/release",
                "bridge_clear_conversation_context_pack",
                {},
            ),
        )
        for path, method, body in routes:
            with self.subTest(path=path), patch.object(
                local_bridge, method, return_value=(staged_payload(), 201)
            ):
                if method in {
                    "bridge_release_conversation_attachment",
                    "bridge_clear_conversation_context_pack",
                }:
                    local_bridge_method_result = (staged_payload(), 200)
                else:
                    local_bridge_method_result = (staged_payload(), 201)
                with patch.object(local_bridge, method, return_value=local_bridge_method_result):
                    status, payload, _headers = self.json_request(
                        "POST",
                        path,
                        body=json.dumps(body).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                self.assertEqual(status, local_bridge_method_result[1])
                self.assertEqual(payload["conversation_id"], CONVERSATION_ID)

        status, payload, _headers = self.json_request(
            "POST",
            f"/bridge/v1/conversations/{CONVERSATION_ID}/workspace-files",
            body=b'{"root_id":"workspace","relative_path":"README.md","path":"/private"}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "bridge_route_not_found"})

    def test_content_route_streams_exact_safe_bytes_with_locked_headers(self):
        item = media_item()
        item.update({
            "mime_type": "text/markdown",
            "kind": "text",
            "byte_size": 5,
            "state": "attached",
        })
        with patch.object(
            local_bridge,
            "bridge_conversation_attachment_content",
            return_value=(item, io.BytesIO(b"hello"), 200),
        ):
            status, body, headers = self.request(
                "GET",
                f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments/{ATTACHMENT_ID}/content",
            )

        self.assertEqual(status, 200)
        self.assertEqual(body, b"hello")
        self.assertEqual(headers["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(headers["Content-Length"], "5")
        self.assertEqual(headers["Cache-Control"], "private, no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(headers["Content-Security-Policy"], "default-src 'none'; sandbox")

        image = media_item()
        image.update({
            "mime_type": "image/png",
            "kind": "image",
            "byte_size": 4,
            "state": "attached",
        })
        with patch.object(
            local_bridge,
            "bridge_conversation_attachment_content",
            return_value=(image, io.BytesIO(b"\x89PNG"), 200),
        ):
            status, body, headers = self.request(
                "GET",
                f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments/{ATTACHMENT_ID}/content",
            )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"\x89PNG")
        self.assertEqual(headers["Content-Type"], "image/png")

    def test_projection_rejects_paths_hashes_and_unowned_content_shapes(self):
        hostile = staged_payload()
        hostile["attachments"][0]["storage_key"] = "aa/private"
        with self.assertRaises(local_bridge.BridgeConversationFileProjectionError):
            local_bridge._ready_staged_context(hostile)

        item = media_item()
        item["name"] = "../secret.txt"
        with self.assertRaises(local_bridge.BridgeConversationFileProjectionError):
            local_bridge._safe_attachment_item(item, staged=False)

        item = media_item()
        item["mime_type"] = "application/pdf"
        with self.assertRaises(local_bridge.BridgeConversationFileProjectionError):
            local_bridge._safe_attachment_item(item, staged=False)

        with patch.object(
            local_bridge,
            "bridge_conversation_attachment_content",
            return_value=(
                {"schema_version": 1, "status": "not_found"},
                None,
                404,
            ),
        ):
            status, payload, _headers = self.json_request(
                "GET",
                f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments/{ATTACHMENT_ID}/content",
            )
        self.assertEqual(status, 404)
        self.assertEqual(payload["status"], "not_found")

    def test_raw_upload_and_content_are_end_to_end_conversation_bound(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = conversation_repository_with_test_agent(root)
            first = repository.create(agent_id=TEST_AGENT_ID).conversation.id
            second = repository.create(agent_id=TEST_AGENT_ID).conversation.id
            with patch.object(server, "DATA_DIR", root):
                status, uploaded, _headers = self.json_request(
                    "POST",
                    f"/bridge/v1/conversations/{first}/attachments",
                    body=b"reviewed",
                    headers={
                        "Content-Type": "text/plain",
                        "Content-Length": "8",
                        local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: "notes.txt",
                    },
                )
                self.assertEqual(status, 201)
                attachment_id = uploaded["attachments"][0]["id"]

                status, body, headers = self.request(
                    "GET",
                    f"/bridge/v1/conversations/{first}/attachments/{attachment_id}/content",
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, b"reviewed")
                self.assertEqual(headers["Content-Length"], "8")

                status, denied, _headers = self.json_request(
                    "GET",
                    f"/bridge/v1/conversations/{second}/attachments/{attachment_id}/content",
                )
                self.assertEqual(status, 404)
                self.assertEqual(denied["status"], "not_found")

    def test_bridge_arrival_sequence_keeps_late_staged_read_behind_upload(self):
        upload_entered = threading.Event()
        release_upload = threading.Event()
        read_entered = threading.Event()
        responses = {}

        def upload_result(*_args, **_kwargs):
            upload_entered.set()
            release_upload.wait(timeout=5)
            return staged_payload(), 201

        def staged_result(_conversation_id):
            read_entered.set()
            return staged_payload(), 200

        def upload_request():
            responses["upload"] = self.json_request(
                "POST",
                f"/bridge/v1/conversations/{CONVERSATION_ID}/attachments",
                body=b"hello",
                headers={
                    "Content-Type": "text/plain",
                    "Content-Length": "5",
                    local_bridge.BRIDGE_UPLOAD_FILENAME_HEADER: "notes.txt",
                },
            )

        def staged_request():
            responses["staged"] = self.json_request(
                "GET",
                f"/bridge/v1/conversations/{CONVERSATION_ID}/staged-context",
            )

        with patch.object(
            local_bridge,
            "bridge_stage_conversation_upload",
            side_effect=upload_result,
        ), patch.object(
            local_bridge,
            "bridge_conversation_staged_context_payload",
            side_effect=staged_result,
        ):
            upload = threading.Thread(target=upload_request)
            staged = threading.Thread(target=staged_request)
            upload.start()
            self.assertTrue(upload_entered.wait(timeout=2))
            staged.start()
            self.assertFalse(read_entered.wait(timeout=0.1))
            release_upload.set()
            upload.join(timeout=2)
            staged.join(timeout=2)

        self.assertTrue(read_entered.is_set())
        self.assertEqual(responses["upload"][0], 201)
        self.assertEqual(responses["staged"][0], 200)

    def test_agent_attachment_enable_route_is_exact_and_projects_no_binding(self):
        success = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "agent": {
                "id": "agent_researcher",
                "name": "Researcher",
                "runtime_type": "hermes",
                "system_role": None,
                "capabilities": ["run.attachments", "run.start"],
            },
        }
        with patch.object(
            local_bridge,
            "bridge_enable_agent_attachments",
            return_value=(success, 200),
        ):
            status, payload, _headers = self.json_request(
                "POST",
                "/bridge/v1/agents/agent_researcher/attachments/enable",
                body=b'{"expected_capabilities":["run.start"]}',
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload, success)
        self.assertNotIn("runtime_agent_ref", json.dumps(payload))
        self.assertNotIn("runtime_config_id", json.dumps(payload))

        status_payload = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "agent_id": "agent_researcher",
            "state": "available",
        }
        with patch.object(
            local_bridge,
            "bridge_agent_attachment_enable_status",
            return_value=(status_payload, 200),
        ):
            status, payload, _headers = self.json_request(
                "GET",
                "/bridge/v1/agents/agent_researcher/attachments/enable",
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload, status_payload)

        status, payload, _headers = self.json_request(
            "POST",
            "/bridge/v1/agents/agent_researcher/attachments/enable",
            body=b'{"expected_capabilities":["run.start","run.start"]}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "bridge_route_not_found"})

        hostile = {
            "schema_version": 1,
            "agent": {
                **success["agent"],
                "runtime_agent_ref": "private-profile",
            },
        }
        with self.assertRaises(local_bridge.BridgeAgentProjectionError):
            local_bridge._ready_agent_attachment_payload(
                hostile,
                "agent_researcher",
            )


class ConversationFileServerTests(unittest.TestCase):
    def test_prepared_input_cleanup_failure_does_not_skip_runtime_shutdown(self):
        with server.AGENT_CONSOLE_INPUT_LOCK:
            prior = dict(server.AGENT_CONSOLE_PREPARED_INPUTS)
            server.AGENT_CONSOLE_PREPARED_INPUTS.clear()
            server.AGENT_CONSOLE_PREPARED_INPUTS["run_shutdown_cleanup"] = ()
        try:
            with patch.object(
                server,
                "stop_agent_console_processes",
            ), patch.object(
                server,
                "cleanup_run_input_directory",
                side_effect=OSError("blocked"),
            ), patch.object(server.CODEX_RUNTIME, "close") as close:
                server.shutdown_agent_runtimes()
            close.assert_called_once_with()
        finally:
            with server.AGENT_CONSOLE_INPUT_LOCK:
                server.AGENT_CONSOLE_PREPARED_INPUTS.clear()
                server.AGENT_CONSOLE_PREPARED_INPUTS.update(prior)

    def test_staged_read_waits_behind_the_exact_python_upload_lock(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = conversation_repository_with_test_agent(root)
            conversation = repository.create(agent_id=TEST_AGENT_ID).conversation.id
            entered = threading.Event()
            release = threading.Event()
            finished = threading.Event()
            result = {}

            def hold_upload_lock():
                with server.HERMES_CONNECTION_OPERATION_LOCK:
                    entered.set()
                    release.wait(timeout=5)

            def read_staging():
                result["value"] = server.mentat_conversation_staged_context_payload(
                    conversation
                )
                finished.set()

            with patch.object(server, "DATA_DIR", root):
                holder = threading.Thread(target=hold_upload_lock)
                reader = threading.Thread(target=read_staging)
                holder.start()
                self.assertTrue(entered.wait(timeout=2))
                reader.start()
                self.assertFalse(finished.wait(timeout=0.1))
                release.set()
                holder.join(timeout=2)
                reader.join(timeout=2)

            self.assertTrue(finished.is_set())
            self.assertEqual(result["value"][1], 200)

    def test_context_pack_note_read_pins_parent_against_symlink_swap(self):
        if not server._OS_OPEN_SUPPORTS_DIR_FD or not hasattr(os, "symlink"):
            self.skipTest("descriptor-relative no-follow reads unavailable")
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            nested = vault / "nested"
            outside = root / "outside"
            nested.mkdir(parents=True)
            outside.mkdir()
            (nested / "Plan.md").write_bytes(b"safe note")
            (outside / "Plan.md").write_bytes(b"outside secret")
            held = vault / "held"
            original_open = os.open
            swapped = False

            def racing_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == "Plan.md" and kwargs.get("dir_fd") is not None and not swapped:
                    nested.rename(held)
                    nested.symlink_to(outside, target_is_directory=True)
                    swapped = True
                return original_open(path, flags, *args, **kwargs)

            try:
                with (
                    patch.object(server, "OBSIDIAN_VAULT", vault),
                    patch.object(server.os, "open", side_effect=racing_open),
                ):
                    content = server._read_context_pack_note("nested/Plan.md")
            finally:
                if nested.is_symlink():
                    nested.unlink()
                if held.exists():
                    held.rename(nested)

            self.assertTrue(swapped)
            self.assertEqual(content, b"safe note")

            with patch.object(server, "OBSIDIAN_VAULT", vault), patch.object(
                server,
                "_OS_OPEN_SUPPORTS_DIR_FD",
                False,
            ), self.assertRaises(Exception):
                server._read_context_pack_note("nested/Plan.md")

    def test_runtime_handoff_preserves_remote_runs_without_context_and_accepts_eight_trusted_files(self):
        context = RuntimeContext(
            agent_id="agent_hermes",
            runtime_agent_ref="default",
            mentat_run_id="run_context_handoff",
            dispatch_id="turn_context_handoff",
        )
        with patch.object(
            server,
            "_start_agent_console_run_locked",
            return_value=({"status": "accepted"}, 202),
        ) as start, patch.object(
            server,
            "agent_console_history_is_current",
            return_value=True,
        ), patch.object(
            server,
            "agent_console_storage_degraded",
            return_value=False,
        ):
            server._start_hermes_runtime_task(
                SimpleNamespace(id="task_context_handoff", objective="Run without files"),
                context,
            )
        self.assertIsNone(start.call_args.kwargs["trusted_attachment_ids"])

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            identifiers = [
                create_attachment(
                    root,
                    original_name=f"context-{index}.txt",
                    content=f"context {index}".encode(),
                )["id"]
                for index in range(8)
            ]
            with patch.object(server, "DATA_DIR", root):
                rejected, error = server.prepare_agent_console_attachments(identifiers)
                self.assertEqual(rejected, [])
                self.assertIn("at most 5 files", error)
                prepared, error = server.prepare_agent_console_attachments(
                    identifiers,
                    maximum=8,
                )
            self.assertIsNone(error)
            self.assertEqual([item["id"] for item in prepared], identifiers)

    @unittest.skipUnless(
        server.SECURE_DIR_FD_DELETE,
        "secure POSIX directory descriptors required",
    )
    def test_pre_admission_input_materialization_is_digest_verified_and_atomic(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = create_attachment(root, original_name="first.txt", content=b"first")
            second = create_attachment(root, original_name="second.txt", content=b"second")
            resolve_blob_path(root, second["id"]).write_bytes(b"tamper")
            run_id = "run_prepared_inputs"

            with patch.object(server, "DATA_DIR", root):
                with self.assertRaises(Exception):
                    server.prepare_mentat_conversation_run_inputs(
                        run_id,
                        (first["id"], second["id"]),
                    )

            self.assertFalse(
                (root / "runtime" / "agent-console-inputs" / run_id).exists()
            )
            self.assertNotIn(run_id, server.AGENT_CONSOLE_PREPARED_INPUTS)

            crash_run_id = "run_crash_orphan"
            with patch.object(server, "DATA_DIR", root):
                server.prepare_mentat_conversation_run_inputs(
                    crash_run_id,
                    (first["id"],),
                )
                with patch.object(
                    server,
                    "active_agent_console_run_ids",
                    return_value=(),
                ), patch.object(
                    server,
                    "garbage_collect_console_attachments",
                    return_value={},
                ), patch(
                    "conversation_attachments.reconcile_staged_contexts",
                    return_value={"staged_references_removed": 0},
                ):
                    report = server.maintain_agent_console_attachments()
                self.assertEqual(report["run_input_snapshots_removed"], 0)
                with patch.object(
                    server,
                    "read_task_snapshot",
                    return_value=[],
                ), patch.object(
                    server,
                    "active_agent_console_run_ids",
                    return_value=(),
                ), patch.object(
                    server,
                    "reconcile_task_artifact_bindings",
                    return_value=(),
                ), patch.object(
                    server,
                    "reconcile_console_attachments",
                    return_value={},
                ), patch(
                    "conversation_attachments.reconcile_staged_contexts",
                    return_value={"staged_references_removed": 0},
                ):
                    startup_report = server.maintain_agent_console_attachments(
                        startup=True
                    )
                self.assertEqual(
                    startup_report["run_input_snapshots_removed"],
                    0,
                )
                self.assertTrue(
                    (root / "runtime" / "agent-console-inputs" / crash_run_id).exists()
                )
                server.cleanup_mentat_conversation_run_inputs(crash_run_id)
                server.prepare_mentat_conversation_run_inputs(
                    crash_run_id,
                    (first["id"],),
                )
                server.AGENT_CONSOLE_PREPARED_INPUTS.clear()
                removed = server.reconcile_run_input_directories(
                    root,
                    active_run_ids=(),
                )
            self.assertEqual(removed, 1)
            self.assertFalse(
                (root / "runtime" / "agent-console-inputs" / crash_run_id).exists()
            )

    def test_input_materialization_fails_before_write_without_secure_cleanup(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            attachment = create_attachment(
                root,
                original_name="context.txt",
                content=b"context",
            )
            run_id = "run_insecure_cleanup"
            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "SECURE_DIR_FD_DELETE",
                False,
            ), self.assertRaises(AttachmentUnavailable):
                server.prepare_mentat_conversation_run_inputs(
                    run_id,
                    (attachment["id"],),
                )
            self.assertFalse(
                (root / "runtime" / "agent-console-inputs" / run_id).exists()
            )
            self.assertNotIn(run_id, server.AGENT_CONSOLE_PREPARED_INPUTS)

    def test_agent_attachment_enable_is_explicit_runtime_checked_and_revision_bound(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = AgentRegistry(
                root,
                supported_runtime_types=server.AGENT_RUNTIME_REGISTRY.runtime_types,
            )
            registry.create_agent(
                agent_id="agent_researcher",
                name="Researcher",
                runtime_config_id="runtime_researcher",
                runtime_type="hermes",
                runtime_agent_ref="researcher",
                capabilities=("run.start",),
            )
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(
                    server.HERMES_RUNTIME,
                    "supports_attachments",
                    return_value=True,
                ) as supports,
            ):
                eligibility, status = server.mentat_agent_attachment_enable_status(
                    "agent_researcher"
                )
                self.assertEqual(status, 200)
                self.assertEqual(eligibility["state"], "available")
                enabled, status = server.enable_mentat_agent_attachments(
                    "agent_researcher",
                    {"expected_capabilities": ["run.start"]},
                )
                self.assertEqual(status, 200)
                self.assertEqual(
                    enabled["agent"]["capabilities"],
                    ["run.attachments", "run.start"],
                )
                self.assertNotIn("runtime_agent_ref", json.dumps(enabled))
                self.assertEqual(supports.call_count, 2)
                supports.assert_called_with("researcher")

                eligibility, status = server.mentat_agent_attachment_enable_status(
                    "agent_researcher"
                )
                self.assertEqual(status, 200)
                self.assertEqual(eligibility["state"], "enabled")

                stale, status = server.enable_mentat_agent_attachments(
                    "agent_researcher",
                    {"expected_capabilities": ["run.start"]},
                )
                self.assertEqual(status, 409)
                self.assertEqual(stale["error_code"], "agent_attachment.conflict")

            registry.create_agent(
                agent_id="agent_other",
                name="Other",
                runtime_config_id="runtime_other",
                runtime_type="hermes",
                runtime_agent_ref="other",
                capabilities=("run.start",),
            )
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(
                    server.HERMES_RUNTIME,
                    "supports_attachments",
                    return_value=False,
                ),
            ):
                unsupported, status = server.enable_mentat_agent_attachments(
                    "agent_other",
                    {"expected_capabilities": ["run.start"]},
                )
                self.assertEqual(status, 415)
                self.assertEqual(
                    unsupported["error_code"],
                    "agent_attachment.unsupported",
                )

    def test_upload_refresh_content_release_and_cross_conversation_denial(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = conversation_repository_with_test_agent(root)
            first = repository.create(agent_id=TEST_AGENT_ID).conversation.id
            second = repository.create(agent_id=TEST_AGENT_ID).conversation.id
            with patch.object(server, "DATA_DIR", root):
                uploaded, status = server.stage_mentat_conversation_upload(
                    first,
                    original_name="notes.md",
                    content_type="text/markdown",
                    content=b"safe context",
                )
                self.assertEqual(status, 201)
                self.assertEqual(uploaded["conversation_id"], first)
                attachment = uploaded["attachments"][0]
                self.assertNotIn("path", json.dumps(uploaded))
                self.assertNotIn("sha256", json.dumps(uploaded))

                refreshed, status = server.mentat_conversation_staged_context_payload(first)
                self.assertEqual(status, 200)
                self.assertEqual(refreshed, uploaded)

                bridged, status = local_bridge.bridge_conversation_staged_context_payload(
                    first
                )
                self.assertEqual(status, 200)
                self.assertEqual(bridged["status"], "ready")
                self.assertEqual(bridged["attachments"][0]["id"], attachment["id"])

                metadata, content, status = server.mentat_conversation_attachment_content(
                    first,
                    attachment["id"],
                )
                self.assertEqual(status, 200)
                self.assertTrue(metadata["available"])
                try:
                    self.assertEqual(content.read(), b"safe context")
                finally:
                    content.close()

                bridge_metadata, bridge_content, status = (
                    local_bridge.bridge_conversation_attachment_content(
                        first,
                        attachment["id"],
                    )
                )
                self.assertEqual(status, 200)
                try:
                    self.assertEqual(bridge_content.read(), b"safe context")
                finally:
                    bridge_content.close()
                self.assertEqual(bridge_metadata["id"], attachment["id"])

                denied, content, status = server.mentat_conversation_attachment_content(
                    second,
                    attachment["id"],
                )
                self.assertEqual(status, 404)
                self.assertIsNone(content)
                self.assertEqual(denied, {"error_code": "conversation_file.not_found"})

                released, status = server.release_mentat_conversation_attachment(
                    first,
                    attachment["id"],
                )
                self.assertEqual(status, 200)
                self.assertEqual(released["attachments"], [])

    def test_workspace_and_context_pack_capabilities_use_only_relative_authority(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            vault = root / "vault"
            workspace.mkdir()
            vault.mkdir()
            (workspace / "README.md").write_text("# Workspace\n", encoding="utf-8")
            (vault / "Plan.md").write_text("# Reviewed plan\n", encoding="utf-8")
            repository = conversation_repository_with_test_agent(root)
            conversation = repository.create(agent_id=TEST_AGENT_ID).conversation.id
            pack = {
                "schema_version": 1,
                "id": PACK_ID,
                "name": "Delivery",
                "description": "One reviewed note",
                "instructions": "Use the reviewed plan.",
                "note_paths": ["Plan.md"],
                "workspace_files": [],
                "created_at": "2026-08-29T12:00:00Z",
                "updated_at": "2026-08-29T12:00:00Z",
            }
            (root / "context_packs.json").write_text(
                json.dumps([pack]), encoding="utf-8"
            )
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "CONFIGURED_DATA_DIR", root),
                patch.object(server, "BASE_DIR", workspace),
                patch.object(server, "OBSIDIAN_VAULT", vault),
            ):
                searched, status = server.mentat_workspace_files_payload("readme")
                self.assertEqual(status, 200)
                self.assertEqual(searched["files"][0]["path"], "README.md")
                self.assertNotIn(str(workspace), json.dumps(searched))

                staged, status = server.stage_mentat_workspace_file(
                    conversation,
                    {"root_id": "workspace", "relative_path": "README.md"},
                )
                self.assertEqual(status, 201)
                self.assertEqual(staged["attachments"][0]["source"], "workspace")

                summaries, status = server.mentat_context_pack_summaries_payload()
                self.assertEqual(status, 200)
                summary = summaries["context_packs"][0]
                self.assertEqual(
                    set(summary),
                    {"id", "name", "description", "revision", "item_count"},
                )

                conflict, status = server.apply_mentat_conversation_context_pack(
                    conversation,
                    PACK_ID,
                    {"expected_revision": PACK_REVISION},
                )
                self.assertEqual(status, 409)
                self.assertEqual(conflict["error_code"], "conversation_file.conflict")

                applied, status = server.apply_mentat_conversation_context_pack(
                    conversation,
                    PACK_ID,
                    {"expected_revision": summary["revision"]},
                )
                if not server._OS_OPEN_SUPPORTS_DIR_FD:
                    self.assertEqual(status, 410)
                    self.assertEqual(
                        applied,
                        {"error_code": "conversation_file.unavailable"},
                    )
                    remaining, remaining_status = (
                        server.mentat_conversation_staged_context_payload(
                            conversation
                        )
                    )
                    self.assertEqual(remaining_status, 200)
                    self.assertIsNone(remaining["context_pack"])
                    self.assertEqual(
                        [item["source"] for item in remaining["attachments"]],
                        ["workspace"],
                    )
                    return
                self.assertEqual(status, 201)
                self.assertEqual(applied["context_pack"]["id"], PACK_ID)
                self.assertEqual(
                    [item["source"] for item in applied["attachments"]],
                    ["workspace", "context_pack"],
                )
                with closing(connect(root)) as connection:
                    evidence = staged_context_evidence(connection, conversation)
                self.assertTrue(server.conversation_context_pack_is_current(
                    applied["context_pack"],
                    tuple(evidence["context_pack_source_digests"]),
                ))
                (vault / "Plan.md").write_text("# Tampered plan\n", encoding="utf-8")
                self.assertFalse(server.conversation_context_pack_is_current(
                    applied["context_pack"],
                    tuple(evidence["context_pack_source_digests"]),
                ))

                rejected_clear, status = server.clear_mentat_conversation_context_pack(
                    conversation,
                    {"force": True},
                )
                self.assertEqual(status, 400)
                self.assertEqual(rejected_clear["error_code"], "conversation_file.invalid")

                cleared, status = server.clear_mentat_conversation_context_pack(
                    conversation,
                    {},
                )
                self.assertEqual(status, 200)
                self.assertIsNone(cleared["context_pack"])
                self.assertEqual(
                    [item["source"] for item in cleared["attachments"]],
                    ["workspace"],
                )


if __name__ == "__main__":
    unittest.main()
