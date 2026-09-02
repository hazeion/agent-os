from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mentat import local_bridge
from project_repository import ensure_project_sqlite_authority
import server
from task_repository import (
    ensure_task_sqlite_authority,
    read_authoritative_task_snapshot,
)


NOW = "2026-09-02T12:00:00Z"
PROJECT = {
    "id": "project_alpha",
    "name": "Alpha",
    "type": "project",
    "status": "active",
    "description": "",
    "obsidian_note": None,
    "aliases": [],
    "created_at": NOW,
    "updated_at": NOW,
}
TASK = {
    "id": "task_alpha",
    "title": "Plan Alpha",
    "description": "A bounded test Task.",
    "project": "Alpha",
    "status": "todo",
    "priority": "medium",
    "assignee": None,
    "due_date": None,
    "source": "dashboard",
    "tags": [],
    "review_required": False,
    "needs_attention": False,
    "created_at": NOW,
    "updated_at": NOW,
    "completed_at": None,
    "workflow_stage": "inbox",
    "planning_state": "inbox",
}


class PlanningTaskIntegrationTests(unittest.TestCase):
    def _authority_root(self, root: Path) -> None:
        (root / "tasks.json").write_text(json.dumps([TASK]), encoding="utf-8")
        (root / "projects.json").write_text(json.dumps([PROJECT]), encoding="utf-8")
        ensure_task_sqlite_authority(root)
        ensure_project_sqlite_authority(root)

    @contextmanager
    def _server_patches(self, root: Path, vault: Path):
        with (
            patch.object(server, "DATA_DIR", root),
            patch.object(server, "CONFIGURED_DATA_DIR", root),
            patch.object(server, "DATA_MUTATION_LOCK", True),
            patch.object(server, "OBSIDIAN_VAULT", vault),
        ):
            yield

    def test_browser_reminder_replace_is_exact_and_cannot_set_delivery_state(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            vault.mkdir()
            self._authority_root(root)
            original = {
                "id": "reminder_alpha",
                "at": "2026-09-03T09:00:00-07:00",
                "channel": "browser",
                "enabled": True,
                "notified_at": "2026-09-03T09:00:00-07:00",
            }
            snapshot = read_authoritative_task_snapshot(root, "task_alpha")
            candidate = dict(snapshot.document)
            candidate["reminders"] = [original]
            from task_repository import replace_authoritative_task

            replace_authoritative_task(root, candidate, expected_revision=snapshot.revision)

            with (
                self._server_patches(root, vault),
                patch.object(server, "update_task", side_effect=AssertionError("legacy mutation must not run")),
            ):
                before = read_authoritative_task_snapshot(root, "task_alpha")
                response, status = server.replace_mentat_planning_task_reminders(
                    "task_alpha",
                    {
                        "expected_revision": before.revision,
                        "reminders": [{
                            "id": "reminder_alpha",
                            # This is the portable UTC spelling provided by the
                            # selected-Task detail route.
                            "at": "2026-09-03T16:00:00Z",
                            "enabled": True,
                        }],
                    },
                )
                self.assertEqual((status, response["action"]), (200, "replace_reminders"))
                stored = read_authoritative_task_snapshot(root, "task_alpha")
                self.assertEqual(stored.revision, before.revision + 1)
                self.assertEqual(stored.document["reminders"], [original])
                self.assertIn("notified_at", response["task"]["reminders"][0])

                changed, changed_status = server.replace_mentat_planning_task_reminders(
                    "task_alpha",
                    {
                        "expected_revision": stored.revision,
                        "reminders": [{
                            "id": "reminder_alpha",
                            "at": "2026-09-03T16:01:00Z",
                            "enabled": True,
                        }],
                    },
                )
                self.assertEqual((changed_status, changed["action"]), (200, "replace_reminders"))
                self.assertNotIn(
                    "notified_at",
                    read_authoritative_task_snapshot(root, "task_alpha").document["reminders"][0],
                )

                invalid, invalid_status = server.replace_mentat_planning_task_reminders(
                    "task_alpha",
                    {
                        "expected_revision": stored.revision + 1,
                        "reminders": [{
                            "id": "reminder_alpha",
                            "at": "2026-09-03T16:01:00Z",
                            "enabled": True,
                            "notified_at": "2026-09-03T16:01:00Z",
                        }],
                    },
                )
                self.assertEqual((invalid_status, invalid), (400, {"error_code": "planning.task_invalid"}))
                stale, stale_status = server.replace_mentat_planning_task_reminders(
                    "task_alpha",
                    {"expected_revision": before.revision, "reminders": []},
                )
                self.assertEqual((stale_status, stale), (409, {"error_code": "planning.task_conflict"}))

    def test_note_attach_requires_regular_vault_markdown_and_detach_survives_file_removal(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            note = vault / "Plans" / "Alpha.md"
            note.parent.mkdir(parents=True)
            note.write_text("private note body", encoding="utf-8")
            self._authority_root(root)
            with (
                self._server_patches(root, vault),
                patch.object(server, "attach_task_note", side_effect=AssertionError("legacy note mutation must not run")),
                patch.object(server, "detach_task_note", side_effect=AssertionError("legacy note mutation must not run")),
            ):
                initial = read_authoritative_task_snapshot(root, "task_alpha")
                attached, attached_status = server.attach_mentat_planning_task_note(
                    "task_alpha", {"expected_revision": initial.revision, "path": "Plans/Alpha.md"}
                )
                self.assertEqual((attached_status, attached["action"]), (200, "attach_note"))
                self.assertEqual(attached["task"]["note_links"], [{"path": "Plans/Alpha.md", "title": "Alpha"}])
                after_attach = read_authoritative_task_snapshot(root, "task_alpha")
                self.assertEqual(after_attach.document["note_links"], [{"path": "Plans/Alpha.md", "title": "Alpha"}])

                note.unlink()
                detached, detached_status = server.detach_mentat_planning_task_note(
                    "task_alpha", {"expected_revision": after_attach.revision, "path": "Plans/Alpha.md"}
                )
                self.assertEqual((detached_status, detached["action"]), (200, "detach_note"))
                self.assertEqual(detached["task"]["note_links"], [])
                unsafe, unsafe_status = server.attach_mentat_planning_task_note(
                    "task_alpha", {"expected_revision": after_attach.revision + 1, "path": "../outside.md"}
                )
                self.assertEqual((unsafe_status, unsafe), (400, {"error_code": "planning.note_invalid"}))

    def test_note_picker_is_bounded_and_returns_only_safe_references(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            notes = vault / "Plans"
            notes.mkdir(parents=True)
            for index in range(52):
                (notes / f"Note-{index:02d}.md").write_text("private", encoding="utf-8")
            self._authority_root(root)
            with self._server_patches(root, vault):
                payload = server.mentat_planning_note_picker_payload("Note")
                self.assertEqual((payload["available"], payload["count"], payload["truncated"]), (True, 50, True))
                self.assertNotIn("private", str(payload))
                self.assertNotIn(str(vault), str(payload))
                self.assertEqual(payload["notes"][0], {"path": "Plans/Note-00.md", "title": "Note-00"})

    def test_note_attach_rejects_a_symlink_even_when_its_target_is_inside_the_vault(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            vault.mkdir()
            target = vault / "Target.md"
            target.write_text("private", encoding="utf-8")
            link = vault / "Link.md"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("this Windows test environment does not permit symlink creation")
            self._authority_root(root)
            with self._server_patches(root, vault):
                snapshot = read_authoritative_task_snapshot(root, "task_alpha")
                response, status = server.attach_mentat_planning_task_note(
                    "task_alpha", {"expected_revision": snapshot.revision, "path": "Link.md"}
                )
                self.assertEqual((status, response), (400, {"error_code": "planning.note_invalid"}))

    def test_calendar_link_is_fresh_primary_only_and_unlink_is_exact(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            vault.mkdir()
            self._authority_root(root)
            fresh_source = {
                "source": "google",
                "auth": "connected",
                "calendar": "primary",
                "read_only": True,
                "window": {
                    "start": "2026-09-06T00:00:00-07:00",
                    "end": "2026-09-13T00:00:00-07:00",
                },
                "timezone": {"id": "America/Los_Angeles"},
                "items": [{
                    "id": "event_focus",
                    "title": "Fresh Focus",
                    "start": "2026-09-08T13:00:00-07:00",
                    "end": "2026-09-08T14:00:00-07:00",
                    "all_day": False,
                }],
            }
            with (
                self._server_patches(root, vault),
                patch.object(server, "google_calendar_events", return_value=fresh_source) as read_calendar,
                patch.object(server, "link_task_calendar_event", side_effect=AssertionError("legacy mutation must not run")),
                patch.object(server, "unlink_task_calendar_event", side_effect=AssertionError("legacy mutation must not run")),
            ):
                initial = read_authoritative_task_snapshot(root, "task_alpha")
                linked, linked_status = server.link_mentat_planning_task_calendar_event(
                    "task_alpha", {
                        "expected_revision": initial.revision,
                        "event_id": "event_focus",
                        "week_start": "2026-09-06",
                        "timezone": "America/Los_Angeles",
                    },
                )
                self.assertEqual((linked_status, linked["action"]), (200, "calendar_link"))
                read_calendar.assert_called_once_with(
                    days=7, limit=250, start="2026-09-06",
                    timezone_name="America/Los_Angeles", refresh=True,
                )
                after_link = read_authoritative_task_snapshot(root, "task_alpha")
                self.assertEqual(after_link.document["calendar_links"], [{
                    "calendar_id": "primary", "event_id": "event_focus", "label": "Fresh Focus",
                }])

                unlinked, unlinked_status = server.unlink_mentat_planning_task_calendar_event(
                    "task_alpha", {
                        "expected_revision": after_link.revision,
                        "calendar_id": "primary",
                        "event_id": "event_focus",
                    },
                )
                self.assertEqual((unlinked_status, unlinked["action"]), (200, "calendar_unlink"))
                self.assertEqual(
                    read_authoritative_task_snapshot(root, "task_alpha").document["calendar_links"],
                    [],
                )

                stale, stale_status = server.link_mentat_planning_task_calendar_event(
                    "task_alpha", {
                        "expected_revision": initial.revision,
                        "event_id": "event_focus",
                        "week_start": "2026-09-06",
                        "timezone": "America/Los_Angeles",
                    },
                )
                self.assertEqual((stale_status, stale), (409, {"error_code": "planning.task_conflict"}))

    def test_bridge_projects_fixed_picker_and_detail_mutations(self):
        project = {"id": "project_alpha", "name": "Alpha", "status": "active", "revision": 1}
        task = {
            "id": "task_alpha", "title": "Plan Alpha", "project_id": "project_alpha",
            "project_name": "Alpha", "status": "todo", "priority": "medium",
            "due_date": None, "planned_for_today": False, "planning_state": "inbox",
            "workflow_stage": "inbox", "deferred": False, "blocked": False, "revision": 2,
            "needs_attention": False, "review_required": False, "attention_reasons": [],
            "updated_at": NOW, "description": "A bounded test Task.", "tags": [],
            "estimated_minutes": None, "scheduled_block": None, "recurrence": None,
            "reminders": [], "subtasks": [], "calendar_links": [], "note_links": [],
            "assigned_agent_id": None,
        }
        source = {"schema_version": 1, "action": "replace_reminders", "project": project, "task": task}
        with patch.object(server, "replace_mentat_planning_task_reminders", return_value=(source, 200)) as call:
            payload, status = local_bridge.bridge_replace_planning_task_reminders_payload(
                "task_alpha", {"expected_revision": 1, "reminders": []}
            )
        self.assertEqual((status, payload["action"], payload["task"]["id"]), (200, "replace_reminders", "task_alpha"))
        call.assert_called_once_with("task_alpha", {"expected_revision": 1, "reminders": []})

        picker_source = {
            "schema_version": 1, "query": "Alpha", "notes": [{"path": "Plans/Alpha.md", "title": "Alpha"}],
            "count": 1, "truncated": False, "available": True,
        }
        with patch.object(server, "mentat_planning_note_picker_payload", return_value=picker_source):
            picker, picker_status = local_bridge.bridge_planning_note_picker_payload("Alpha")
        self.assertEqual((picker_status, picker["notes"]), (200, picker_source["notes"]))
        unsafe_source = {**picker_source, "notes": [{"path": "C:/private/Alpha.md", "title": "Alpha"}]}
        with patch.object(server, "mentat_planning_note_picker_payload", return_value=unsafe_source):
            rejected, rejected_status = local_bridge.bridge_planning_note_picker_payload("Alpha")
        self.assertEqual((rejected_status, rejected["status"]), (500, "error"))

    def test_bridge_calendar_window_and_mutations_are_fixed(self):
        window_request = {"week_start": "2026-09-06", "timezone": "America/Los_Angeles"}
        window_source = {
            "schema_version": 1, "calendar_id": "primary",
            "week_start": "2026-09-06", "week_end": "2026-09-13",
            "timezone": "America/Los_Angeles", "label": "September 6–12, 2026",
            "events": [{
                "id": "event_focus", "title": "Focus",
                "start": "2026-09-08T20:00:00Z", "end": "2026-09-08T21:00:00Z",
                "all_day": False,
            }],
            "event_count": 1, "read_only": True,
        }
        with patch.object(
            server, "mentat_planning_calendar_window_payload", return_value=(window_source, 200)
        ) as read:
            window, window_status = local_bridge.bridge_planning_calendar_window_payload(window_request)
        self.assertEqual((window_status, window["events"]), (200, window_source["events"]))
        self.assertNotIn("description", str(window))
        read.assert_called_once_with(window_request)
        invalid, invalid_status = local_bridge.bridge_planning_calendar_window_payload({
            "week_start": "2026-09-07", "timezone": "America/Los_Angeles",
        })
        self.assertEqual((invalid_status, invalid["status"]), (400, "invalid"))

        project = {"id": "project_alpha", "name": "Alpha", "status": "active", "revision": 1}
        task = {
            "id": "task_alpha", "title": "Plan Alpha", "project_id": "project_alpha",
            "project_name": "Alpha", "status": "todo", "priority": "medium",
            "due_date": None, "planned_for_today": False, "planning_state": "inbox",
            "workflow_stage": "inbox", "deferred": False, "blocked": False, "revision": 2,
            "needs_attention": False, "review_required": False, "attention_reasons": [],
            "updated_at": NOW, "description": "A bounded test Task.", "tags": [],
            "estimated_minutes": None, "scheduled_block": None, "recurrence": None,
            "reminders": [], "subtasks": [], "calendar_links": [], "note_links": [],
            "assigned_agent_id": None,
        }
        linked_source = {"schema_version": 1, "action": "calendar_link", "project": project, "task": task}
        link_request = {"expected_revision": 1, "event_id": "event_focus", **window_request}
        with patch.object(
            server, "link_mentat_planning_task_calendar_event", return_value=(linked_source, 200)
        ) as link:
            linked, linked_status = local_bridge.bridge_link_planning_task_calendar_payload("task_alpha", link_request)
        self.assertEqual((linked_status, linked["action"]), (200, "calendar_link"))
        link.assert_called_once_with("task_alpha", link_request)

        unlink_request = {"expected_revision": 2, "calendar_id": "primary", "event_id": "event_focus"}
        unlinked_source = {**linked_source, "action": "calendar_unlink"}
        with patch.object(
            server, "unlink_mentat_planning_task_calendar_event", return_value=(unlinked_source, 200)
        ) as unlink:
            unlinked, unlinked_status = local_bridge.bridge_unlink_planning_task_calendar_payload("task_alpha", unlink_request)
        self.assertEqual((unlinked_status, unlinked["action"]), (200, "calendar_unlink"))
        unlink.assert_called_once_with("task_alpha", unlink_request)
