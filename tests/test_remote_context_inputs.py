from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from hermes_transport import RemoteHermesConsoleTransport, TransportBinding
import server


PNG = b"\x89PNG\r\n\x1a\n" + b"safe-image-payload"


class FakeContextClient:
    def __init__(self, *, on_discovery=None):
        self.discovery_calls = 0
        self.submitted = []
        self.on_discovery = on_discovery

    def require_console_run_capabilities(self):
        self.discovery_calls += 1
        if self.on_discovery is not None:
            self.on_discovery()
        return {
            "model": "anthropic/claude-test",
            "capabilities": [
                "run_submission",
                "run_status",
                "run_events_sse",
                "run_stop",
            ],
        }

    def submit_run(self, prompt):
        self.submitted.append(prompt)
        return {"run_id": "run_" + ("a" * 32), "status": "started"}


class RemoteContextInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.vault = self.root / "vault"
        self.data.mkdir()
        self.vault.mkdir()
        (self.data / "context_packs.json").write_text("[]\n", encoding="utf-8")
        (self.vault / "Private Plan.md").write_text(
            "ORIGINAL SNAPSHOT\nShip the bounded slice.\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(server, "DATA_DIR", self.data),
            patch.object(server, "CONFIGURED_DATA_DIR", self.data),
            patch.object(server, "OBSIDIAN_VAULT", self.vault),
        ]
        for item in self.patches:
            item.start()
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_REMOTE_WORKERS.clear()
        with server.REMOTE_CONTEXT_STAGE_LOCK:
            server.REMOTE_CONTEXT_STAGES.clear()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_REMOTE_WORKERS.clear()
        with server.REMOTE_CONTEXT_STAGE_LOCK:
            server.REMOTE_CONTEXT_STAGES.clear()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def adapter(self, client=None, *, binding_id="b" * 32):
        return RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", binding_id),
            client=client or FakeContextClient(),
        )

    def create_pack(self, *, instructions="Return a concise result."):
        response, status = server.create_context_pack({
            "name": f"Remote delivery {instructions}",
            "description": "Private project context",
            "instructions": instructions,
            "note_paths": ["Private Plan.md"],
            "workspace_files": [],
        })
        self.assertEqual(status, 201)
        return response["context_pack"]

    def stage(self, adapter, pack_id):
        with patch.object(server, "hermes_console_transport", return_value=adapter):
            response, status = server.stage_context_pack(pack_id)
        self.assertEqual(status, 201)
        self.assertRegex(response["remote_context_token"], r"^context_[0-9a-f]{32}$")
        self.assertTrue(response["instructions_in_remote_context"])
        self.assertNotIn(str(self.vault), json.dumps(response))
        return response

    def start(self, adapter, request):
        with patch.object(server, "hermes_console_transport", return_value=adapter), patch.object(
            adapter, "revalidate"
        ), patch.object(server.threading, "Thread") as worker, patch.object(
            server, "persist_agent_console_runs"
        ):
            response, status = server.start_agent_console_run(request)
        return response, status, worker

    def test_exact_staged_snapshot_builds_path_free_bounded_prompt_and_binds_run(self):
        client = FakeContextClient()
        adapter = self.adapter(client)
        pack = self.create_pack()
        staged = self.stage(adapter, pack["id"])
        attachment_id = staged["attachments"][0]["id"]
        (self.vault / "Private Plan.md").write_text("CHANGED AFTER STAGE\n", encoding="utf-8")

        response, status, worker = self.start(adapter, {
            "agent_id": "default",
            "prompt": "Use the project context.",
            "attachment_ids": [attachment_id],
            "remote_context_token": staged["remote_context_token"],
        })

        self.assertEqual(status, 202)
        run = server.AGENT_CONSOLE_RUNS[response["run"]["id"]]
        outbound = run["_execution_prompt"]
        self.assertIn("ORIGINAL SNAPSHOT", outbound)
        self.assertNotIn("CHANGED AFTER STAGE", outbound)
        self.assertIn("Context item 1", outbound)
        for private_value in (
            "Private Plan.md",
            str(self.vault),
            str(self.data),
            attachment_id,
            staged["remote_context_token"],
            "Remote workshop",
        ):
            self.assertNotIn(private_value, outbound)
        self.assertLessEqual(len(outbound), server.AGENT_CONSOLE_PROMPT_LIMIT)
        self.assertEqual(response["run"]["attachments"][0]["id"], attachment_id)
        self.assertNotIn("_execution_prompt", response["run"])
        worker.return_value.start.assert_called_once_with()

        server.AGENT_CONSOLE_RUNS.clear()
        replay, replay_status, _ = self.start(adapter, {
            "agent_id": "default",
            "prompt": "Replay",
            "attachment_ids": [attachment_id],
            "remote_context_token": staged["remote_context_token"],
        })
        self.assertEqual(replay_status, 409)
        self.assertIn("already used", replay["error"])
        self.assertEqual(client.submitted, [])

    def test_changed_pack_connection_ids_and_expiry_fail_before_discovery(self):
        cases = ("revision", "connection", "ids", "expiry")
        for case in cases:
            with self.subTest(case=case):
                server.AGENT_CONSOLE_RUNS.clear()
                with server.REMOTE_CONTEXT_STAGE_LOCK:
                    server.REMOTE_CONTEXT_STAGES.clear()
                client = FakeContextClient()
                staged_adapter = self.adapter(client)
                pack = self.create_pack(instructions=f"Instructions for {case}")
                staged = self.stage(staged_adapter, pack["id"])
                request_adapter = staged_adapter
                ids = [item["id"] for item in staged["attachments"]]
                if case == "revision":
                    update = {
                        **pack,
                        "instructions": "Changed after staging.",
                    }
                    _, update_status = server.update_context_pack(pack["id"], update)
                    self.assertEqual(update_status, 200)
                elif case == "connection":
                    request_adapter = self.adapter(client, binding_id="c" * 32)
                elif case == "ids":
                    ids = []
                else:
                    with server.REMOTE_CONTEXT_STAGE_LOCK:
                        server.REMOTE_CONTEXT_STAGES[staged["remote_context_token"]]["expires_at"] = 0

                response, status, _ = self.start(request_adapter, {
                    "agent_id": "default",
                    "prompt": "Work",
                    "attachment_ids": ids,
                    "remote_context_token": staged["remote_context_token"],
                })
                self.assertEqual(status, 409)
                self.assertTrue(any(word in response["error"].lower() for word in ("changed", "expired", "apply")))
                self.assertEqual(client.discovery_calls, 0)
                self.assertEqual(client.submitted, [])

    def test_direct_text_and_artifact_transfer_degrade_and_images_require_the_exact_capability(self):
        client = FakeContextClient()
        adapter = self.adapter(client)
        text, _ = server.create_agent_console_attachment(
            original_name="notes.txt",
            content_type="text/plain",
            content=b"private text\n",
        )
        image, _ = server.create_agent_console_attachment(
            original_name="diagram.png",
            content_type="image/png",
            content=PNG,
        )
        cases = (
            ({"attachment_ids": [text["attachment"]["id"]]}, "text through a context pack only"),
            ({"attachment_ids": [image["attachment"]["id"]]}, "safe runs image input"),
            ({"artifact_ids": ["artifact_" + ("a" * 32)]}, "artifact transfer"),
        )
        for extra, message in cases:
            with self.subTest(message=message):
                response, status, _ = self.start(adapter, {
                    "agent_id": "default",
                    "prompt": "Work",
                    **extra,
                })
                self.assertEqual(status, 409)
                self.assertIn(message, response["error"].lower())
        # The console capability discovery is now required before a remote
        # start. Text and artifacts still fail closed; an image needs the exact
        # advertised Runs image capability rather than a generic upload route.
        self.assertEqual(client.discovery_calls, 2)
        self.assertEqual(client.submitted, [])

    def test_large_snapshot_is_deterministically_truncated_and_total_overflow_fails(self):
        (self.vault / "Private Plan.md").write_text("x" * 20_000, encoding="utf-8")
        client = FakeContextClient()
        adapter = self.adapter(client)
        pack = self.create_pack(instructions="Keep the result short.")
        staged = self.stage(adapter, pack["id"])
        request = {
            "agent_id": "default",
            "prompt": "Review",
            "attachment_ids": [staged["attachments"][0]["id"]],
            "remote_context_token": staged["remote_context_token"],
        }
        response, status, _ = self.start(adapter, request)
        self.assertEqual(status, 202)
        execution = server.AGENT_CONSOLE_RUNS[response["run"]["id"]]["_execution_prompt"]
        self.assertIn("[Context item truncated by Mentat]", execution)
        self.assertLessEqual(execution.count("x"), server.REMOTE_CONTEXT_ITEM_LIMIT)

        server.AGENT_CONSOLE_RUNS.clear()
        staged = self.stage(adapter, pack["id"])
        response, status, _ = self.start(adapter, {
            "agent_id": "default",
            "prompt": "p" * 19_000,
            "attachment_ids": [staged["attachments"][0]["id"]],
            "remote_context_token": staged["remote_context_token"],
        })
        self.assertEqual(status, 409)
        self.assertIn("too large", response["error"].lower())
        self.assertEqual(client.submitted, [])

    def test_instruction_only_and_attachment_only_packs_supply_a_generic_prompt(self):
        adapter = self.adapter()
        instruction_response, status = server.create_context_pack({
            "name": "Instructions only",
            "description": "",
            "instructions": "Summarize the current delivery state.",
            "note_paths": [],
            "workspace_files": [],
        })
        self.assertEqual(status, 201)
        staged = self.stage(adapter, instruction_response["context_pack"]["id"])
        response, status, _ = self.start(adapter, {
            "agent_id": "default",
            "prompt": "",
            "attachment_ids": [],
            "remote_context_token": staged["remote_context_token"],
        })
        self.assertEqual(status, 202)
        self.assertEqual(
            response["run"]["prompt"],
            "Use the staged Context Pack to complete the request.",
        )

        server.AGENT_CONSOLE_RUNS.clear()
        attachment_pack = self.create_pack(instructions="")
        staged = self.stage(adapter, attachment_pack["id"])
        response, status, _ = self.start(adapter, {
            "agent_id": "default",
            "prompt": "",
            "attachment_ids": [staged["attachments"][0]["id"]],
            "remote_context_token": staged["remote_context_token"],
        })
        self.assertEqual(status, 202)
        self.assertIn("ORIGINAL SNAPSHOT", server.AGENT_CONSOLE_RUNS[response["run"]["id"]]["_execution_prompt"])

    def test_pack_edit_or_delete_during_discovery_fails_before_queueing(self):
        for mutation in ("edit", "delete"):
            with self.subTest(mutation=mutation):
                server.AGENT_CONSOLE_RUNS.clear()
                result = {}
                client = FakeContextClient()
                adapter = self.adapter(client)
                pack = self.create_pack(instructions=f"Old private context for {mutation}.")
                staged = self.stage(adapter, pack["id"])

                def mutate():
                    if mutation == "edit":
                        changed = {**pack, "instructions": "Replacement context."}
                        result["response"], result["status"] = server.update_context_pack(pack["id"], changed)
                    else:
                        result["response"], result["status"] = server.delete_context_pack(
                            pack["id"],
                            {"confirmed": True, "expected_revision": pack["revision"]},
                        )

                client.on_discovery = mutate
                response, status, worker = self.start(adapter, {
                    "agent_id": "default",
                    "prompt": "Work",
                    "attachment_ids": [staged["attachments"][0]["id"]],
                    "remote_context_token": staged["remote_context_token"],
                })
                self.assertEqual(result["status"], 200)
                self.assertEqual(status, 409)
                self.assertIn("changed", response["error"].lower())
                self.assertEqual(server.AGENT_CONSOLE_RUNS, {})
                self.assertEqual(client.submitted, [])
                worker.return_value.start.assert_not_called()

    def test_same_size_blob_tampering_fails_before_discovery(self):
        client = FakeContextClient()
        adapter = self.adapter(client)
        pack = self.create_pack()
        staged = self.stage(adapter, pack["id"])
        attachment_id = staged["attachments"][0]["id"]
        blob = server.resolve_blob_path(self.data, attachment_id)
        original = blob.read_bytes()
        blob.write_bytes(b"Z" * len(original))

        response, status, _ = self.start(adapter, {
            "agent_id": "default",
            "prompt": "Work",
            "attachment_ids": [attachment_id],
            "remote_context_token": staged["remote_context_token"],
        })
        self.assertEqual(status, 409)
        self.assertIn("changed", response["error"].lower())
        self.assertEqual(client.discovery_calls, 0)
        self.assertEqual(client.submitted, [])

    def test_total_context_limit_includes_instructions_and_snapshot_framing(self):
        (self.vault / "Private Plan.md").write_text("x" * 20_000, encoding="utf-8")
        adapter = self.adapter()
        pack = self.create_pack(instructions="i" * 6_000)
        staged = self.stage(adapter, pack["id"])
        response, status, _ = self.start(adapter, {
            "agent_id": "default",
            "prompt": "Review",
            "attachment_ids": [staged["attachments"][0]["id"]],
            "remote_context_token": staged["remote_context_token"],
        })
        self.assertEqual(status, 202)
        execution = server.AGENT_CONSOLE_RUNS[response["run"]["id"]]["_execution_prompt"]
        _, context = execution.split("\n\n", 1)
        self.assertLessEqual(len(context), server.REMOTE_CONTEXT_CONTENT_LIMIT)
        self.assertIn("User instructions", context)
        self.assertIn("Context item 1", context)

    def test_consuming_oldest_grant_at_exact_capacity_preserves_other_grants(self):
        response, status = server.create_context_pack({
            "name": "Capacity context",
            "description": "",
            "instructions": "Use the capacity-safe context.",
            "note_paths": [],
            "workspace_files": [],
        })
        self.assertEqual(status, 201)
        pack = response["context_pack"]
        tokens = [
            server.register_remote_context_stage(
                binding_id="b" * 32,
                pack=pack,
                attachment_ids=(),
            )
            for _ in range(server.REMOTE_CONTEXT_STAGE_LIMIT)
        ]
        self.assertEqual(len(server.REMOTE_CONTEXT_STAGES), server.REMOTE_CONTEXT_STAGE_LIMIT)

        execution, prepared, binding, error = server.consume_remote_context_stage(
            tokens[0],
            binding_id="b" * 32,
            attachment_ids=(),
            user_prompt="Work",
        )

        self.assertIsNone(error)
        self.assertIn("Use the capacity-safe context", execution)
        self.assertEqual(prepared, [])
        self.assertEqual(binding["pack_id"], pack["id"])
        self.assertEqual(len(server.REMOTE_CONTEXT_STAGES), server.REMOTE_CONTEXT_STAGE_LIMIT - 1)
        self.assertTrue(all(token in server.REMOTE_CONTEXT_STAGES for token in tokens[1:]))


if __name__ == "__main__":
    unittest.main()
