from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import hermes_skills
import server


class CompletedResult:
    def __init__(self, payload=None, *, returncode=0, stdout=None, stderr=""):
        self.returncode = returncode
        self.stdout = json.dumps(payload) if stdout is None and payload is not None else (stdout or "")
        self.stderr = stderr


class HermesSkillAdapterTests(unittest.TestCase):
    def catalog_payload(self):
        return {
            "schema_version": 1,
            "hermes_version": "0.18.2",
            "capabilities": {
                "skills.catalog.read": True,
                "skills.selection.write": True,
            },
            "skills": [
                {
                    "id": "github-issues",
                    "name": "github-issues",
                    "category": "github",
                    "description": "Work with GitHub issues.",
                    "path": "/private/path",
                },
                {
                    "id": "plan",
                    "name": "plan",
                    "category": "software-development",
                    "description": "Create implementation plans.",
                },
            ],
        }

    def test_catalog_uses_runtime_and_exposes_builtin_metadata_only(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return CompletedResult(self.catalog_payload())

        payload = hermes_skills.discover_builtin_skills(
            "/opt/hermes/python", "/home/user/.hermes", cwd="/app", runner=runner
        )

        self.assertEqual(payload["status"], "available")
        self.assertEqual([item["id"] for item in payload["skills"]], ["github-issues", "plan"])
        self.assertNotIn("path", payload["skills"][0])
        self.assertEqual(calls[0][0][:2], ["/opt/hermes/python", "-c"])
        self.assertIn("_read_manifest", calls[0][0][2])

    def test_selection_uses_profile_scoped_runtime_helper(self):
        result_payload = {
            "schema_version": 1,
            "profile_id": "builder",
            "enabled_builtin_skills": ["github-issues", "plan"],
            "disabled_builtin_skills": ["airtable"],
        }
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return CompletedResult(result_payload)

        payload = hermes_skills.apply_builtin_skill_selection(
            "/opt/hermes/python",
            "/home/user/.hermes",
            "builder",
            ["plan", "github-issues"],
            cwd="/app",
            runner=runner,
        )

        self.assertEqual(payload["status"], "applied")
        self.assertEqual(json.loads(calls[0][0][4]), ["github-issues", "plan"])
        self.assertIn("save_disabled_skills", calls[0][0][2])
        self.assertEqual(calls[0][1]["env"]["HERMES_HOME"], "/home/user/.hermes")

    def test_catalog_and_selection_fail_closed_without_leaking_stderr(self):
        failed_catalog = hermes_skills.discover_builtin_skills(
            "/opt/hermes/python",
            "/home/user/.hermes",
            runner=lambda *args, **kwargs: CompletedResult(
                returncode=2, stderr="token sk-secret-value"
            ),
        )

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

        failed_selection = hermes_skills.apply_builtin_skill_selection(
            "/opt/hermes/python", "/home/user/.hermes", "builder", [], runner=timeout
        )

        self.assertEqual(failed_catalog["error"]["code"], "runtime_failed")
        self.assertNotIn("sk-secret-value", json.dumps(failed_catalog))
        self.assertEqual(failed_selection["error"]["code"], "runtime_timeout")

    def test_server_exposes_skill_catalog_route(self):
        expected = {"status": "available", "skills": []}
        with patch.object(server, "hermes_python_path", return_value="/opt/hermes/python"), patch.object(
            server, "discover_builtin_skills", return_value=expected
        ) as discover:
            payload = server.API_ROUTES["/api/hermes/skills/catalog"]()

        self.assertEqual(payload, expected)
        discover.assert_called_once_with("/opt/hermes/python", server.HERMES_HOME, cwd=server.BASE_DIR)


if __name__ == "__main__":
    unittest.main()
