from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import hermes_profile_deletion as deletion
import server


class CompletedResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def discovery(*profile_ids, active="default", delete=True):
    return {
        "schema_version": 1,
        "status": "available",
        "active_profile": active,
        "capabilities": {"profiles.read": True, "profiles.delete": delete},
        "profiles": [
            {"id": profile_id, "name": profile_id, "is_default": profile_id == "default"}
            for profile_id in profile_ids
        ],
    }


class ProfileDeletionContractTests(unittest.TestCase):
    def test_preview_names_destructive_effects_and_binds_confirmation(self):
        payload, status = deletion.preview_profile_deletion(
            "builder", {}, discovery("default", "builder")
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["operation"], "profiles.delete")
        self.assertEqual(payload["normalized"]["profile_id"], "builder")
        self.assertTrue(payload["confirmation_id"].startswith("profile_delete_"))
        self.assertTrue(all("builder" in effect for effect in payload["effects"][:1]))
        self.assertTrue(any("credentials" in effect for effect in payload["effects"]))

    def test_preview_blocks_default_active_missing_and_unavailable(self):
        cases = [
            ("default", discovery("default", "builder"), "default", 409),
            ("builder", discovery("default", "builder", active="builder"), "active", 409),
            ("missing", discovery("default", "builder"), "does not exist", 404),
            ("builder", discovery("default", "builder", delete=False), "does not expose", 503),
        ]
        for name, available, message, expected_status in cases:
            with self.subTest(name=name, status=expected_status):
                payload, status = deletion.preview_profile_deletion(name, {}, available)
                self.assertEqual(status, expected_status)
                self.assertIn(message, payload["error"]["message"])

    def test_runtime_deletion_uses_fixed_argv_and_hides_runtime_output(self):
        runner = unittest.mock.Mock(return_value=CompletedResult(stdout=json.dumps({"schema_version": 1, "ok": True})))
        payload = deletion.delete_hermes_profile(
            "/opt/hermes/python", "/home/user/.hermes", "builder", cwd="/app", runner=runner
        )

        self.assertEqual(payload, {"status": "deleted", "profile_id": "builder"})
        args = runner.call_args.args[0]
        self.assertEqual(args[0:2], ["/opt/hermes/python", "-c"])
        self.assertEqual(args[-1], "builder")
        self.assertNotIn("shell", runner.call_args.kwargs)
        self.assertIn("delete_profile(name, yes=True)", deletion.HERMES_PROFILE_DELETION_SCRIPT)
        self.assertIn("redirect_stdout", deletion.HERMES_PROFILE_DELETION_SCRIPT)

    def test_runtime_failures_are_generic_and_do_not_leak_stderr(self):
        failed = deletion.delete_hermes_profile(
            "/opt/hermes/python",
            "/home/user/.hermes",
            "builder",
            runner=lambda *args, **kwargs: CompletedResult(returncode=2, stderr="token sk-secret"),
        )
        self.assertEqual(failed["error_code"], "runtime_failed")
        self.assertNotIn("sk-secret", json.dumps(failed))

        timed_out = deletion.delete_hermes_profile(
            "/opt/hermes/python",
            "/home/user/.hermes",
            "builder",
            runner=unittest.mock.Mock(side_effect=subprocess.TimeoutExpired(["python"], 60)),
        )
        self.assertTrue(timed_out["partial"])


class ProfileDeletionServerTests(unittest.TestCase):
    def setUp(self):
        server.AGENT_CONSOLE_RUNS.clear()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        if server.HERMES_PROFILE_CREATION_LOCK.locked():
            server.HERMES_PROFILE_CREATION_LOCK.release()

    def confirmed(self):
        preview, status = deletion.preview_profile_deletion(
            "builder", {}, discovery("default", "builder")
        )
        self.assertEqual(status, 200)
        return {"confirmed": True, "confirmation_id": preview["confirmation_id"]}

    def test_delete_requires_matching_confirmation_and_revalidation(self):
        missing, missing_status = server.delete_confirmed_hermes_profile("builder", {})
        request = self.confirmed()
        request["confirmation_id"] = "profile_delete_stale"
        with patch.object(server, "hermes_profiles_payload", return_value=discovery("default", "builder")):
            stale, stale_status = server.delete_confirmed_hermes_profile("builder", request)

        self.assertEqual(missing_status, 400)
        self.assertIn("explicit confirmation", missing["error"])
        self.assertEqual(stale_status, 409)
        self.assertIn("changed after preview", stale["error"])

    def test_delete_blocks_active_run_and_shared_profile_mutation(self):
        request = self.confirmed()
        server.AGENT_CONSOLE_RUNS["run_active"] = {"id": "run_active", "status": "running"}
        preview, preview_status = server.preview_hermes_profile_deletion("builder", {})
        blocked, blocked_status = server.delete_confirmed_hermes_profile("builder", request)
        server.AGENT_CONSOLE_RUNS.clear()
        server.HERMES_PROFILE_CREATION_LOCK.acquire()
        locked, locked_status = server.delete_confirmed_hermes_profile("builder", request)
        server.HERMES_PROFILE_CREATION_LOCK.release()

        self.assertEqual(preview_status, 409)
        self.assertEqual(blocked_status, 409)
        self.assertEqual(blocked["active_run_id"], "run_active")
        self.assertEqual(locked_status, 409)
        self.assertIn("profile change", locked["error"])

    def test_delete_refreshes_and_verifies_profile_is_absent(self):
        request = self.confirmed()
        before = discovery("default", "builder")
        after = discovery("default")
        with patch.object(server, "hermes_profiles_payload", side_effect=[before, after]), patch.object(
            server, "delete_hermes_profile", return_value={"status": "deleted", "profile_id": "builder"}
        ) as execute:
            payload, status = server.delete_confirmed_hermes_profile("builder", request)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted_profile_id"], "builder")
        execute.assert_called_once_with(
            server.hermes_python_path(), server.HERMES_HOME, "builder", cwd=server.BASE_DIR
        )

    def test_failure_preserves_refreshed_profile_without_runtime_secrets(self):
        request = self.confirmed()
        before = discovery("default", "builder")
        after = discovery("default", "builder")
        with patch.object(server, "hermes_profiles_payload", side_effect=[before, after]), patch.object(
            server, "delete_hermes_profile", return_value={"status": "failed", "error_code": "runtime_failed"}
        ):
            payload, status = server.delete_confirmed_hermes_profile("builder", request)

        self.assertEqual(status, 500)
        self.assertEqual(payload["profile"]["id"], "builder")
        self.assertNotIn("stderr", json.dumps(payload))

    def test_delete_does_not_report_success_when_refresh_is_unavailable(self):
        request = self.confirmed()
        before = discovery("default", "builder")
        unavailable = {
            "status": "unavailable",
            "profiles": [],
            "capabilities": {"profiles.read": False, "profiles.delete": False},
            "error": {"code": "runtime_unavailable", "message": "offline"},
        }
        with patch.object(
            server, "hermes_profiles_payload", side_effect=[before, unavailable]
        ), patch.object(
            server,
            "delete_hermes_profile",
            return_value={"status": "deleted", "profile_id": "builder"},
        ):
            payload, status = server.delete_confirmed_hermes_profile("builder", request)

        self.assertEqual(status, 503)
        self.assertEqual(payload["error_code"], "verification_unavailable")
        self.assertNotIn("deleted_profile_id", payload)

    def test_routes_are_local_control_post_handlers(self):
        routes = {pattern.pattern: handler.__name__ for pattern, handler, _ in server.POST_ROUTES}
        self.assertEqual(
            routes[r"^/api/hermes/profiles/([^/]+)/delete/preview$"],
            "preview_hermes_profile_deletion",
        )
        self.assertEqual(
            routes[r"^/api/hermes/profiles/([^/]+)/delete$"],
            "delete_confirmed_hermes_profile",
        )


if __name__ == "__main__":
    unittest.main()
