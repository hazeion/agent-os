from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import unittest
from zipfile import ZipFile

from diagnostics_bundle import MAX_DIAGNOSTICS_BYTES, build_diagnostics_bundle


ROOT = Path(__file__).resolve().parents[1]


class DiagnosticsBundleTests(unittest.TestCase):
    def build(self, health=None, **overrides):
        values = {
            "version": "0.1.0b1",
            "display_version": "v0.1.0-beta.1",
            "health": health or {"status": "healthy", "subsystems": []},
            "generated_at": datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
            "platform_name": "Darwin",
            "architecture": "arm64",
            "python_version": "3.13.5",
            "packaged": False,
        }
        values.update(overrides)
        return build_diagnostics_bundle(**values)

    def test_bundle_has_a_fixed_small_allowlisted_shape(self):
        bundle = self.build(
            {
                "status": "degraded",
                "subsystems": [
                    {"key": "remote_hermes", "status": "healthy", "summary": "ignored"},
                    {"key": "host_resources", "status": "degraded", "size": "ignored"},
                ],
            }
        )

        self.assertLess(len(bundle), MAX_DIAGNOSTICS_BYTES)
        with ZipFile(BytesIO(bundle)) as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                ["environment.json", "health.json", "manifest.json", "privacy.json"],
            )
            health = json.loads(archive.read("health.json"))
            environment = json.loads(archive.read("environment.json"))
            manifest = json.loads(archive.read("manifest.json"))
            metadata = [
                (item.date_time, item.create_system, item.external_attr, item.compress_type)
                for item in archive.infolist()
            ]

        self.assertEqual(health["overall"], "degraded")
        self.assertEqual(
            health["subsystems"],
            [
                {"key": "host_resources", "status": "degraded"},
                {"key": "remote_hermes", "status": "healthy"},
            ],
        )
        self.assertEqual(environment["platform"], "macos")
        self.assertEqual(environment["architecture"], "arm64")
        self.assertEqual(manifest["display_version"], "v0.1.0-beta.1")
        self.assertEqual(
            metadata,
            [((1980, 1, 1, 0, 0, 0), 3, (0o100600 & 0xFFFF) << 16, 8)] * 4,
        )

    def test_duplicate_flood_is_deduplicated_and_keeps_the_worst_status(self):
        subsystem_flood = [
            {"key": "calendar", "status": "healthy", "summary": "/private"}
            for _index in range(200_000)
        ]
        subsystem_flood.append({"key": "calendar", "status": "error"})
        subsystem_flood.append({"key": "cron", "status": "degraded"})
        bundle = self.build({"status": "error", "subsystems": subsystem_flood})

        with ZipFile(BytesIO(bundle)) as archive:
            health = json.loads(archive.read("health.json"))
            self.assertLess(sum(item.file_size for item in archive.infolist()), 64 * 1024)
        self.assertEqual(
            health["subsystems"],
            [
                {"key": "calendar", "status": "error"},
                {"key": "cron", "status": "degraded"},
            ],
        )

    def test_hostile_health_and_version_text_never_enters_bundle(self):
        private_values = [
            "sk-secret-value",
            "/Users/private/project",
            "operator@example.com",
            "https://private-hermes.example/api",
            "blob_0123456789abcdef",
            "private conversation text",
        ]
        bundle = self.build(
            {
                "status": private_values[0],
                "summary": private_values[5],
                "subsystems": [
                    {
                        "key": "remote_hermes",
                        "status": "healthy",
                        "summary": private_values[1],
                        "label": private_values[2],
                        "endpoint": private_values[3],
                        "blob": private_values[4],
                    },
                    {"key": private_values[0], "status": "error"},
                ],
            },
            version=private_values[1],
            display_version=private_values[2],
            platform_name=private_values[3],
            architecture=private_values[4],
            python_version=private_values[5],
        )
        raw = bundle.decode("latin-1")
        for private_value in private_values:
            self.assertNotIn(private_value, raw)

    def test_environment_values_are_normalized_to_small_categories(self):
        bundle = self.build(platform_name="FreeBSD/private", architecture="workstation-7", python_version="3.13.5 local")
        with ZipFile(BytesIO(bundle)) as archive:
            environment = json.loads(archive.read("environment.json"))
        self.assertEqual(
            environment,
            {"architecture": "other", "install_type": "python", "platform": "other", "python": "unknown"},
        )


class TrustSupportDocumentTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_readme_is_beginner_first_and_surfaces_preinstall_support(self):
        readme = self.read("README.md")
        self.assertLess(readme.index("## Quick start"), readme.index("## Want the technical details?"))
        self.assertIn("supported platforms and known", readme)
        self.assertIn("SUPPORT.md", readme)
        self.assertIn("PRIVACY.md", readme)
        self.assertIn("SECURITY.md", readme)
        self.assertLess(readme.index("supported platforms and known"), readme.index("git clone"))

    def test_security_privacy_and_support_cover_beta_boundaries(self):
        security = self.read("SECURITY.md")
        privacy = self.read("PRIVACY.md")
        support = self.read("SUPPORT.md")
        self.assertIn("security/advisories/new", security)
        self.assertIn("loopback", security.lower())
        self.assertIn("remote Hermes", security)
        self.assertIn("no default telemetry", privacy)
        self.assertIn("Google Calendar", privacy)
        self.assertIn("Obsidian", privacy)
        self.assertIn("best effort", support)
        self.assertIn("macOS and Windows", support)
        self.assertIn("Known limitations", support)

    def test_issue_templates_keep_security_reports_private(self):
        config = self.read(".github/ISSUE_TEMPLATE/config.yml")
        bug = self.read(".github/ISSUE_TEMPLATE/bug_report.yml")
        self.assertIn("security/advisories/new", config)
        self.assertIn("Never post credentials", bug)
        self.assertNotIn("security issue details", bug.lower())

    def test_settings_exposes_help_version_issue_and_diagnostics_actions(self):
        index = self.read("public/index.html")
        app = self.read("public/app.js")
        core = self.read("public/core.js")
        self.assertIn('id="mentat-version"', index)
        self.assertIn('id="download-diagnostics"', index)
        self.assertIn("issues/new?template=bug_report.yml", index)
        self.assertIn("no logs, paths, credentials, or personal content", index)
        self.assertIn("downloadDiagnosticsBundle", app)
        self.assertIn("'/api/diagnostics/bundle'", core)

    def test_python_package_keeps_license_and_diagnostics_module(self):
        pyproject = self.read("pyproject.toml")
        self.assertIn('license-files = ["LICENSE"]', pyproject)
        self.assertIn('"diagnostics_bundle"', pyproject)


if __name__ == "__main__":
    unittest.main()
