from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import hermes_profile_identity as identity
import server


class CompletedResult:
    def __init__(self, payload=None, *, returncode=0, stdout=None, stderr=""):
        self.returncode = returncode
        self.stdout = json.dumps(payload) if stdout is None and payload is not None else (stdout or "")
        self.stderr = stderr


def discovery(description="Existing role"):
    return {
        "schema_version": 1,
        "status": "available",
        "capabilities": {
            "profiles.read": True,
            "profiles.identity.read": True,
            "profiles.identity.write": True,
        },
        "profiles": [
            {
                "id": "builder",
                "name": "builder",
                "description": description,
                "is_default": False,
            }
        ],
    }


def inspected(status="missing", role_description="Existing role"):
    return {
        "schema_version": 1,
        "profile_id": "builder",
        "status": status,
        "revision": "a" * 64,
        "name": "" if status == "missing" else "builder",
        "role": "" if status == "missing" else role_description,
        "role_description": role_description,
        "error": None,
    }


def synced(role="New role"):
    return {
        "schema_version": 1,
        "profile_id": "builder",
        "status": "synced",
        "revision": "b" * 64,
        "name": "builder",
        "role": role,
        "role_description": role,
        "error": None,
    }


class ProfileIdentityContractTests(unittest.TestCase):
    def test_preview_binds_role_and_current_soul_revision(self):
        first, first_status = identity.preview_profile_identity(
            "builder", {"role": "New role"}, discovery(), inspected()
        )
        changed, changed_status = identity.preview_profile_identity(
            "builder",
            {"role": "New role"},
            discovery(),
            {**inspected(), "revision": "c" * 64},
        )

        self.assertEqual(first_status, 200)
        self.assertEqual(changed_status, 200)
        self.assertNotEqual(first["confirmation_id"], changed["confirmation_id"])
        self.assertEqual(first["operation"], "profiles.identity.write")
        self.assertTrue(any("SOUL.md" in effect for effect in first["effects"]))

    def test_preview_fails_closed_for_conflicts_capability_and_reserved_markup(self):
        conflict, conflict_status = identity.preview_profile_identity(
            "builder", {"role": "New role"}, discovery(), inspected("conflict")
        )
        unavailable_discovery = discovery()
        unavailable_discovery["capabilities"]["profiles.identity.write"] = False
        unavailable, unavailable_status = identity.preview_profile_identity(
            "builder", {"role": "New role"}, unavailable_discovery, inspected()
        )
        markup, markup_status = identity.preview_profile_identity(
            "builder",
            {"role": f"Break {identity.IDENTITY_END_MARKER}"},
            discovery(),
            inspected(),
        )

        self.assertEqual(conflict_status, 409)
        self.assertEqual(conflict["error"]["code"], "identity_conflict")
        self.assertEqual(unavailable_status, 503)
        self.assertEqual(unavailable["error"]["code"], "capability_unavailable")
        self.assertEqual(markup_status, 400)

    def test_runtime_adapter_uses_fixed_python_argv_and_stdin_without_leaking_soul(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return CompletedResult(synced("Routes implementation work."))

        payload = identity.apply_profile_identity(
            "/opt/hermes/python",
            "/home/user/.hermes",
            "builder",
            "Routes implementation work.",
            "a" * 64,
            cwd="/app",
            runner=runner,
        )

        self.assertEqual(payload["status"], "synced")
        self.assertEqual(calls[0][0][:2], ["/opt/hermes/python", "-c"])
        request = json.loads(calls[0][1]["input"])
        self.assertEqual(request["profile_id"], "builder")
        self.assertEqual(request["role"], "Routes implementation work.")
        self.assertNotIn("SOUL.md contents", json.dumps(payload))
        self.assertFalse(calls[0][1]["check"])

    def test_runtime_failures_are_redacted_and_timeout_fails_closed(self):
        failed = identity.inspect_profile_identity(
            "/opt/hermes/python",
            "/home/user/.hermes",
            "builder",
            runner=lambda *args, **kwargs: CompletedResult(
                returncode=2,
                stderr="SOUL secret token sk-private",
            ),
        )

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

        timed_out = identity.inspect_profile_identity(
            "/opt/hermes/python", "/home/user/.hermes", "builder", runner=timeout
        )

        self.assertEqual(failed["error"]["code"], "runtime_failed")
        self.assertNotIn("sk-private", json.dumps(failed))
        self.assertEqual(timed_out["error"]["code"], "runtime_timeout")

    def test_helper_is_scoped_to_managed_block_and_hermes_profile_api(self):
        script = identity.HERMES_PROFILE_IDENTITY_SCRIPT
        self.assertIn("profiles_module.get_profile_dir", script)
        self.assertIn("profiles_module.write_profile_meta", script)
        self.assertIn(identity.IDENTITY_START_MARKER, script)
        self.assertIn("Preserve all SOUL.md content outside", identity.preview_profile_identity(
            "builder", {"role": "New role"}, discovery(), inspected()
        )[0]["effects"][-1])


class ProfileIdentityServerTests(unittest.TestCase):
    def setUp(self):
        server.AGENT_CONSOLE_RUNS.clear()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        if server.HERMES_PROFILE_CREATION_LOCK.locked():
            server.HERMES_PROFILE_CREATION_LOCK.release()

    def confirmed_request(self):
        preview, status = identity.preview_profile_identity(
            "builder", {"role": "New role"}, discovery(), inspected()
        )
        self.assertEqual(status, 200)
        return {
            "role": "New role",
            "confirmed": True,
            "confirmation_id": preview["confirmation_id"],
        }

    def test_confirmed_update_revalidates_applies_and_verifies(self):
        request = self.confirmed_request()
        before_discovery = discovery()
        after_discovery = discovery("New role")
        before = inspected()
        after = synced()
        with patch.object(
            server, "hermes_profiles_payload", side_effect=[before_discovery, after_discovery]
        ), patch.object(
            server, "inspect_profile_identity", side_effect=[before, after]
        ), patch.object(server, "apply_profile_identity", return_value=after) as apply:
            payload, status = server.update_confirmed_hermes_profile_identity("builder", request)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["identity"]["status"], "synced")
        apply.assert_called_once_with(
            server.hermes_python_path(),
            server.HERMES_HOME,
            "builder",
            "New role",
            "a" * 64,
            cwd=server.BASE_DIR,
        )

    def test_update_requires_confirmation_and_blocks_active_console_run(self):
        missing, missing_status = server.update_confirmed_hermes_profile_identity(
            "builder", {"role": "New role"}
        )
        server.AGENT_CONSOLE_RUNS["active"] = {"id": "active", "status": "running"}
        active, active_status = server.update_confirmed_hermes_profile_identity(
            "builder", self.confirmed_request()
        )

        self.assertEqual(missing_status, 400)
        self.assertIn("confirmation", missing["error"])
        self.assertEqual(active_status, 409)
        self.assertEqual(active["active_run_id"], "active")

    def test_identity_routes_are_explicit_local_resources(self):
        post_routes = {pattern.pattern: handler.__name__ for pattern, handler, _ in server.POST_ROUTES}
        get_routes = {pattern.pattern: handler.__name__ for pattern, handler in server.GET_ROUTES.items()}

        self.assertEqual(
            post_routes[r"^/api/hermes/profiles/([^/]+)/identity/preview$"],
            "preview_hermes_profile_identity",
        )
        self.assertEqual(
            post_routes[r"^/api/hermes/profiles/([^/]+)/identity$"],
            "update_confirmed_hermes_profile_identity",
        )
        self.assertEqual(
            get_routes[r"^/api/hermes/profiles/([^/]+)/identity$"],
            "hermes_profile_identity_payload",
        )


if __name__ == "__main__":
    unittest.main()
