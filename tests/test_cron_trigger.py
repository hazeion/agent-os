from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


def cron_job(**overrides) -> dict:
    job = {
        "id": "cron_audit",
        "name": "Audit queue",
        "schedule": "0 9 * * *",
        "enabled": True,
        "prompt": "Review the queue",
        "agent": "default",
        "delivery": "none",
        "last_run": None,
        "next_run": "2026-07-12T09:00:00-07:00",
        "last_status": "idle",
    }
    job.update(overrides)
    return job


class CronTriggerTests(unittest.TestCase):
    def write_jobs(self, root: Path, jobs: list[dict]) -> Path:
        path = root / "jobs.json"
        path.write_text(json.dumps({"jobs": jobs}, indent=2) + "\n", encoding="utf-8")
        return path

    def test_inventory_is_read_only_without_an_atomic_hermes_queue_capability(self):
        with TemporaryDirectory() as tmpdir:
            jobs_path = self.write_jobs(Path(tmpdir), [cron_job()])
            with patch.object(server, "CRON_JOBS", jobs_path):
                payload = server.cron_jobs_payload()

        self.assertEqual(payload["count"], 1)
        self.assertFalse(payload["capabilities"]["crons.queue_enabled"])
        self.assertIn("read-only", payload["queue_error"])

    def test_preview_and_confirmed_queue_fail_closed_without_runtime_mutation(self):
        with TemporaryDirectory() as tmpdir:
            jobs_path = self.write_jobs(Path(tmpdir), [cron_job()])
            with patch.object(server, "CRON_JOBS", jobs_path), patch.object(
                server.subprocess, "run"
            ) as run:
                preview, preview_status = server.preview_cron_trigger("cron_audit")
                payload, status = server.trigger_confirmed_cron(
                    "cron_audit",
                    {"confirmed": True, "confirmation_id": "unsupported-preview"},
                )

        self.assertEqual(preview_status, 503)
        self.assertEqual(preview["error_code"], "atomic_queue_unsupported")
        self.assertEqual(status, 503)
        self.assertEqual(payload["error_code"], "atomic_queue_unsupported")
        run.assert_not_called()

    def test_confirmation_and_job_id_validation_still_fail_before_capability_check(self):
        missing, missing_status = server.trigger_confirmed_cron("cron_audit", {})
        invalid_preview, invalid_preview_status = server.preview_cron_trigger("not/a/job")
        invalid_confirm, invalid_confirm_status = server.trigger_confirmed_cron(
            "not/a/job",
            {"confirmed": True, "confirmation_id": "preview"},
        )

        self.assertEqual(missing_status, 400)
        self.assertIn("explicit confirmation", missing["error"])
        self.assertEqual(invalid_preview_status, 400)
        self.assertEqual(invalid_confirm_status, 400)
        self.assertIn("Invalid cron job id", invalid_preview["error"])
        self.assertIn("Invalid cron job id", invalid_confirm["error"])

    def test_schedule_objects_are_normalized_for_display(self):
        with TemporaryDirectory() as tmpdir:
            jobs_path = self.write_jobs(
                Path(tmpdir),
                [cron_job(schedule={"kind": "interval", "seconds": 300})],
            )
            with patch.object(server, "CRON_JOBS", jobs_path):
                payload = server.read_cron_jobs()

        self.assertEqual(payload["jobs"][0]["schedule"], "every 300s")

    def test_configuration_revision_covers_execution_affecting_fields(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_path = self.write_jobs(root, [cron_job(prompt="First prompt")])
            with patch.object(server, "CRON_JOBS", jobs_path):
                first = server.read_cron_jobs()["jobs"][0]["configuration_revision"]
                self.write_jobs(root, [cron_job(prompt="Different prompt")])
                second = server.read_cron_jobs()["jobs"][0]["configuration_revision"]

        self.assertNotEqual(first, second)

    def test_routes_expose_fail_closed_preview_and_confirm_handlers(self):
        routes = {pattern.pattern: handler.__name__ for pattern, handler, _ in server.POST_ROUTES}
        self.assertEqual(
            routes[r"^/api/hermes/crons/([^/]+)/trigger/preview$"],
            "preview_cron_trigger",
        )
        self.assertEqual(
            routes[r"^/api/hermes/crons/([^/]+)/trigger$"],
            "trigger_confirmed_cron",
        )
        self.assertIs(server.API_ROUTES["/api/hermes/crons"], server.cron_jobs_payload)


if __name__ == "__main__":
    unittest.main()
