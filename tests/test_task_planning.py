from __future__ import annotations

from datetime import date
import unittest

from task_planning import (
    TASK_PLANNING_FIELDS,
    TaskPlanningError,
    normalize_task_planning,
    task_dependencies_satisfied,
    task_matches_saved_view,
    validate_task_planning,
)


class TaskPlanningTests(unittest.TestCase):
    def test_public_planning_field_allowlist_is_explicit(self):
        self.assertIn("planned_for_today", TASK_PLANNING_FIELDS)
        self.assertIn("delegation", TASK_PLANNING_FIELDS)
        self.assertNotIn("command", TASK_PLANNING_FIELDS)

    def test_legacy_task_is_accepted_without_schema_expansion(self):
        legacy = {
            "id": "task_seed",
            "title": "Existing task",
            "status": "todo",
            "custom_existing_field": {"preserved": True},
        }
        self.assertEqual(normalize_task_planning(legacy), legacy)

    def test_normalizes_full_personal_planning_metadata(self):
        task = {
            "id": "task-plan-day",
            "title": "Plan the day",
            "planned_for_today": True,
            "manual_rank": 20,
            "estimated_minutes": 45,
            "scheduled_block": {
                "start": "2026-07-13T09:00:00-07:00",
                "end": "2026-07-13T09:45:00-07:00",
                "label": "Focus",
            },
            "recurrence": {
                "frequency": "weekly",
                "interval": 2,
                "weekdays": ["fri", "mon", "mon"],
                "ends_on": "2026-12-31",
            },
            "recurrence_parent_id": "task-original",
            "reminders": [{"id": "morning", "at": "2026-07-13T08:50:00-07:00"}],
            "subtasks": [{"id": "outline", "title": "Outline", "completed": False}],
            "depends_on": ["task-context", "task-context"],
            "calendar_links": [{"calendar_id": "primary", "event_id": "evt-42"}],
            "note_links": [{"path": "Projects/Mentat plan.md", "title": "Plan"}],
            "planning_state": "planned",
            "delegation": {
                "profile_id": "researcher",
                "board_id": "personal",
                "kanban_task_id": "hermes-task-42",
                "run_id": "run-9",
                "session_id": "session-9",
                "state": "running",
                "sync_state": "synced",
                "review_state": "pending",
                "attempts": 1,
                "summary": "Research is underway.",
                "last_synced_at": "2026-07-13T09:05:00-07:00",
                "audit": [{"at": "2026-07-13T09:00:00-07:00", "actor": "dashboard", "event": "delegated"}],
            },
        }
        normalized = normalize_task_planning(task)
        self.assertEqual(normalized["recurrence"]["weekdays"], ["mon", "fri"])
        self.assertEqual(normalized["recurrence_parent_id"], "task-original")
        self.assertEqual(normalized["reminders"][0]["channel"], "browser")
        self.assertTrue(normalized["reminders"][0]["enabled"])
        self.assertEqual(normalized["subtasks"][0]["rank"], 0)
        self.assertEqual(normalized["depends_on"], ["task-context"])
        self.assertEqual(normalized["delegation"]["run_id"], "run-9")
        self.assertEqual(normalized["delegation"]["review_state"], "pending")
        self.assertEqual(normalized["delegation"]["audit"][0]["event"], "delegated")

    def test_rejects_invalid_types_ranges_and_time_blocks(self):
        invalid = (
            {"planned_for_today": "yes"},
            {"manual_rank": True},
            {"estimated_minutes": 0},
            {"scheduled_block": {"start": "2026-07-13T10:00:00-07:00", "end": "2026-07-13T09:00:00-07:00"}},
            {"recurrence": {"frequency": "hourly"}},
            {"planning_state": "whatever"},
        )
        for task in invalid:
            with self.subTest(task=task), self.assertRaises(TaskPlanningError):
                normalize_task_planning(task)

    def test_rejects_unsafe_note_paths_and_execution_shaped_delegation_data(self):
        paths = ["/Users/alice/private.md", "~/private.md", "C:\\Users\\alice\\private.md", "../private.md", "file:///tmp/private.md"]
        for path in paths:
            with self.subTest(path=path), self.assertRaises(TaskPlanningError):
                normalize_task_planning({"note_links": [{"path": path}]})

        for extra in ({"command": "rm -rf /"}, {"credential_path": "/tmp/key"}, {"token": "secret"}):
            with self.subTest(extra=extra), self.assertRaises(TaskPlanningError):
                normalize_task_planning({"delegation": {"profile_id": "agent", **extra}})

    def test_hermes_metadata_is_limited_to_opaque_safe_references(self):
        unsafe_values = ["/tmp/run", "../run", "agent profile", "file:///tmp/run"]
        for value in unsafe_values:
            with self.subTest(value=value), self.assertRaises(TaskPlanningError):
                normalize_task_planning({"delegation": {"profile_id": value}})

    def test_dependencies_are_unique_and_cannot_reference_self(self):
        with self.assertRaisesRegex(TaskPlanningError, "cannot depend on itself"):
            normalize_task_planning({"id": "task-a", "depends_on": ["task-a"]})
        self.assertTrue(task_dependencies_satisfied({"depends_on": ["task-a"]}, {"task-a", "task-b"}))
        self.assertFalse(task_dependencies_satisfied({"depends_on": ["task-c"]}, {"task-a", "task-b"}))

    def test_saved_views_derive_from_planning_and_delegation_state(self):
        today = date(2026, 7, 13)
        self.assertTrue(task_matches_saved_view({"planned_for_today": True}, "today", on_date=today))
        self.assertTrue(
            task_matches_saved_view(
                {"scheduled_block": {"start": "2026-07-13T09:00:00-07:00", "end": "2026-07-13T10:00:00-07:00"}},
                "today",
                on_date=today,
            )
        )
        self.assertTrue(task_matches_saved_view({"delegation": {"profile_id": "agent", "state": "running"}}, "waiting"))
        self.assertTrue(task_matches_saved_view({"delegation": {"profile_id": "agent", "state": "ready_for_review"}}, "review"))
        self.assertFalse(task_matches_saved_view({"planning_state": "done", "planned_for_today": True}, "today"))
        self.assertTrue(task_matches_saved_view({"status": "completed"}, "completed"))

    def test_non_raising_validator_matches_server_helper_convention(self):
        normalized, error = validate_task_planning({"estimated_minutes": 30})
        self.assertEqual(normalized["estimated_minutes"], 30)
        self.assertIsNone(error)
        normalized, error = validate_task_planning({"estimated_minutes": "30"})
        self.assertIsNone(normalized)
        self.assertIn("estimated_minutes", error)


if __name__ == "__main__":
    unittest.main()
