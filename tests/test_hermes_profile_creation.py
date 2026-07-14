from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import hermes_profile_creation as creation
import server


class CompletedResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def discovery(*profile_ids):
    return {
        "schema_version": 1,
        "status": "available",
        "capabilities": {
            "profiles.read": True,
            "profiles.create": True,
            "profiles.identity.read": True,
            "profiles.identity.write": True,
        },
        "profiles": [
            {"id": profile_id, "name": profile_id, "is_default": profile_id == "default"}
            for profile_id in profile_ids
        ],
    }


def skill_catalog(*skill_ids):
    return {
        "schema_version": 1,
        "status": "available",
        "capabilities": {"skills.catalog.read": True, "skills.selection.write": True},
        "skills": [{"id": skill_id, "name": skill_id} for skill_id in skill_ids],
    }


def identity_before(profile_id="builder"):
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "status": "missing",
        "revision": "a" * 64,
        "name": "",
        "role": "",
        "role_description": "",
        "error": None,
    }


def identity_after(profile_id="builder", role="Builds Mentat features."):
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "status": "synced",
        "revision": "b" * 64,
        "name": profile_id,
        "role": role,
        "role_description": role,
        "error": None,
    }


class HermesProfileCreationContractTests(unittest.TestCase):
    def test_preview_fresh_no_skills_is_confirmable_and_shell_free(self):
        payload, status = creation.preview_profile_creation(
            {
                "name": "Research_Agent",
                "description": "Researches implementation options.",
                "mode": "fresh",
                "seed_skills": False,
            },
            discovery("default"),
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["normalized"]["name"], "research_agent")
        self.assertEqual(payload["command"]["program"], "hermes")
        self.assertEqual(
            payload["command"]["arguments"],
            [
                "profile", "create", "research_agent", "--no-alias",
                "--description=Researches implementation options.", "--no-skills",
            ],
        )
        self.assertTrue(payload["confirmation_id"].startswith("profile_create_"))

    def test_preview_clone_discloses_copied_identity_and_credentials(self):
        payload, status = creation.preview_profile_creation(
            {
                "name": "builder",
                "mode": "clone_config",
                "source_profile": "default",
                "seed_skills": True,
            },
            discovery("default"),
        )

        self.assertEqual(status, 200)
        self.assertIn("--clone-from=default", payload["command"]["arguments"])
        self.assertTrue(any("SOUL.md" in effect for effect in payload["effects"]))
        self.assertTrue(any("credentials" in warning for warning in payload["warnings"]))

    def test_preview_custom_skills_validates_catalog_and_changes_confirmation(self):
        default, default_status = creation.preview_profile_creation(
            {"name": "builder", "skill_mode": "default"},
            discovery("default"),
        )
        custom, custom_status = creation.preview_profile_creation(
            {
                "name": "builder",
                "skill_mode": "custom",
                "enabled_builtin_skills": ["plan", "github-issues"],
            },
            discovery("default"),
            skill_catalog("github-issues", "plan", "airtable"),
        )

        self.assertEqual(default_status, 200)
        self.assertEqual(custom_status, 200)
        self.assertNotEqual(default["confirmation_id"], custom["confirmation_id"])
        self.assertEqual(custom["normalized"]["enabled_builtin_skills"], ["github-issues", "plan"])
        self.assertTrue(any("2 selected" in effect for effect in custom["effects"]))

        unknown, unknown_status = creation.preview_profile_creation(
            {
                "name": "builder",
                "skill_mode": "custom",
                "enabled_builtin_skills": ["not-a-hermes-skill"],
            },
            discovery("default"),
            skill_catalog("plan"),
        )
        self.assertEqual(unknown_status, 400)
        self.assertIn("Unknown built-in skills", unknown["error"]["message"])

    def test_preview_rejects_unsupported_or_ambiguous_inputs(self):
        cases = [
            ({"name": "default"}, "reserved", 400),
            ({"name": "chat"}, "reserved", 400),
            ({"name": "existing"}, "already exists", 409),
            ({"name": "new", "unexpected": True}, "Unsupported", 400),
            ({"name": "new", "mode": "clone_config"}, "source_profile", 400),
            (
                {"name": "new", "mode": "clone_config", "source_profile": "missing"},
                "does not exist",
                404,
            ),
            (
                {
                    "name": "new", "mode": "clone_config", "source_profile": "default",
                    "seed_skills": False,
                },
                "skill_mode cannot be 'none'",
                400,
            ),
            ({"name": "new", "source_profile": "default"}, "only allowed", 400),
        ]
        for request, message, expected_status in cases:
            with self.subTest(request=request):
                payload, status = creation.preview_profile_creation(request, discovery("default", "existing"))
                self.assertEqual(status, expected_status)
                self.assertIn(message, payload["error"]["message"])

    def test_preview_fails_closed_without_create_capability(self):
        unavailable = discovery("default")
        unavailable["capabilities"]["profiles.create"] = False
        payload, status = creation.preview_profile_creation({"name": "builder"}, unavailable)

        self.assertEqual(status, 503)
        self.assertEqual(payload["error"]["code"], "capability_unavailable")


class HermesProfileCreationServerTests(unittest.TestCase):
    def setUp(self):
        server.AGENT_CONSOLE_RUNS.clear()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        if server.HERMES_PROFILE_CREATION_LOCK.locked():
            server.HERMES_PROFILE_CREATION_LOCK.release()

    def confirmed_request(self):
        request = {"name": "builder", "description": "Builds Mentat features.", "mode": "fresh"}
        preview, status = creation.preview_profile_creation(request, discovery("default"))
        self.assertEqual(status, 200)
        return {**request, "confirmed": True, "confirmation_id": preview["confirmation_id"]}

    def test_create_requires_confirmation_and_matching_preview(self):
        missing, missing_status = server.create_hermes_profile({"name": "builder"})
        stale_request = self.confirmed_request()
        stale_request["description"] = "Changed after preview."
        with patch.object(server, "hermes_profiles_payload", return_value=discovery("default")):
            stale, stale_status = server.create_hermes_profile(stale_request)

        self.assertEqual(missing_status, 400)
        self.assertIn("explicit confirmation", missing["error"])
        self.assertEqual(stale_status, 409)
        self.assertIn("changed after preview", stale["error"])

    def test_create_uses_fixed_argv_and_returns_refreshed_profile(self):
        request = self.confirmed_request()
        before = discovery("default")
        after = discovery("default", "builder")
        with patch.object(server, "hermes_profiles_payload", side_effect=[before, after]), patch.object(
            server, "hermes_command_path", return_value="/opt/hermes/bin/hermes"
        ), patch.object(server.subprocess, "run", return_value=CompletedResult()) as run, patch.object(
            server, "inspect_profile_identity", return_value=identity_before()
        ), patch.object(server, "apply_profile_identity", return_value=identity_after()):
            payload, status = server.create_hermes_profile(request)

        self.assertEqual(status, 201)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["profile"]["id"], "builder")
        self.assertEqual(
            run.call_args.args[0],
            [
                "/opt/hermes/bin/hermes", "profile", "create", "builder", "--no-alias",
                "--description=Builds Mentat features.",
            ],
        )
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertFalse(run.call_args.kwargs["check"])

    def test_create_applies_confirmed_custom_skill_selection(self):
        request = {
            "name": "builder",
            "description": "Builds Mentat features.",
            "mode": "fresh",
            "skill_mode": "custom",
            "enabled_builtin_skills": ["plan", "github-issues"],
        }
        catalog = skill_catalog("github-issues", "plan", "airtable")
        preview, status = creation.preview_profile_creation(request, discovery("default"), catalog)
        self.assertEqual(status, 200)
        confirmed = {**request, "confirmed": True, "confirmation_id": preview["confirmation_id"]}
        before = discovery("default")
        after = discovery("default", "builder")
        applied = {
            "status": "applied",
            "profile_id": "builder",
            "enabled_builtin_skills": ["github-issues", "plan"],
            "disabled_builtin_skills": ["airtable"],
        }
        with patch.object(server, "hermes_profiles_payload", side_effect=[before, after]), patch.object(
            server, "hermes_skill_catalog_payload", return_value=catalog
        ), patch.object(server, "hermes_command_path", return_value="/opt/hermes/bin/hermes"), patch.object(
            server.subprocess, "run", return_value=CompletedResult()
        ), patch.object(server, "apply_builtin_skill_selection", return_value=applied) as apply_selection:
            with patch.object(server, "inspect_profile_identity", return_value=identity_before()), patch.object(
                server, "apply_profile_identity", return_value=identity_after()
            ):
                payload, create_status = server.create_hermes_profile(confirmed)

        self.assertEqual(create_status, 201)
        self.assertEqual(payload["skill_selection"], applied)
        apply_selection.assert_called_once_with(
            server.hermes_python_path(),
            server.HERMES_HOME,
            "builder",
            ["github-issues", "plan"],
            cwd=server.BASE_DIR,
        )

    def test_failure_does_not_return_stderr_secrets_and_reports_partial_creation(self):
        request = self.confirmed_request()
        with patch.object(
            server, "hermes_profiles_payload", side_effect=[discovery("default"), discovery("default", "builder")]
        ), patch.object(server, "hermes_command_path", return_value="/opt/hermes/bin/hermes"), patch.object(
            server.subprocess,
            "run",
            return_value=CompletedResult(returncode=2, stderr="token sk-secret-value"),
        ):
            payload, status = server.create_hermes_profile(request)

        self.assertEqual(status, 500)
        self.assertTrue(payload["partial"])
        self.assertNotIn("sk-secret-value", json.dumps(payload))

    def test_timeout_requires_profile_refresh_before_retry(self):
        request = self.confirmed_request()
        with patch.object(server, "hermes_profiles_payload", return_value=discovery("default")), patch.object(
            server, "hermes_command_path", return_value="/opt/hermes/bin/hermes"
        ), patch.object(
            server.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["hermes", "profile", "create"], 180),
        ):
            payload, status = server.create_hermes_profile(request)

        self.assertEqual(status, 504)
        self.assertTrue(payload["partial"])
        self.assertIn("Refresh profiles", payload["error"])

    def test_creation_and_console_runs_are_mutually_exclusive(self):
        request = self.confirmed_request()
        server.HERMES_PROFILE_CREATION_LOCK.acquire()
        blocked_create, blocked_create_status = server.create_hermes_profile(request)
        with patch.object(server, "hermes_command_path", return_value="/opt/hermes/bin/hermes"):
            blocked_run, blocked_run_status = server.start_agent_console_run(
                {"agent_id": "hermes", "prompt": "hello"}
            )
        server.HERMES_PROFILE_CREATION_LOCK.release()

        server.AGENT_CONSOLE_RUNS["run_active"] = {"id": "run_active", "status": "running"}
        with patch.object(server, "hermes_profiles_payload", return_value=discovery("default")):
            active, active_status = server.create_hermes_profile(request)

        self.assertEqual(blocked_create_status, 409)
        self.assertEqual(blocked_run_status, 409)
        self.assertEqual(active_status, 409)
        self.assertEqual(active["active_run_id"], "run_active")

    def test_post_routes_dispatch_preview_and_creation(self):
        with patch.object(server, "hermes_profiles_payload", return_value=discovery("default")):
            preview, preview_status = server.handle_post_route(
                "/api/hermes/profiles/preview", {"name": "builder"}
            )
        routes = {pattern.pattern: handler.__name__ for pattern, handler, _ in server.POST_ROUTES}

        self.assertEqual(preview_status, 200)
        self.assertTrue(preview["valid"])
        self.assertEqual(routes[r"^/api/hermes/profiles/preview$"], "preview_hermes_profile_creation")
        self.assertEqual(routes[r"^/api/hermes/profiles$"], "create_hermes_profile")


if __name__ == "__main__":
    unittest.main()
