from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


class FakeCalendarRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class FakeCalendarEvents:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCalendarRequest(self.response)


class FakeCalendarService:
    def __init__(self, response, calls):
        self.resource = FakeCalendarEvents(response, calls)

    def events(self):
        return self.resource


class PaginatedCalendarEvents:
    def __init__(self, responses, calls):
        self.responses = list(responses)
        self.calls = calls

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCalendarRequest(self.responses.pop(0))


class PaginatedCalendarService:
    def __init__(self, responses, calls):
        self.resource = PaginatedCalendarEvents(responses, calls)

    def events(self):
        return self.resource


class CalendarWeekBackendTests(unittest.TestCase):
    def setUp(self):
        server.CALENDAR_CACHE.update({"key": None, "payload": None, "fetched_at": None})

    def tearDown(self):
        server.CALENDAR_CACHE.update({"key": None, "payload": None, "fetched_at": None})

    def write_calendar(self, root: Path, events: list[dict]) -> None:
        (root / "calendar.json").write_text(json.dumps(events), encoding="utf-8")

    def test_exact_sunday_week_filters_local_fallback_by_overlap(self):
        events = [
            {
                "id": "overlap-start",
                "title": "Carries into Sunday",
                "start": "2026-07-11T23:30:00-07:00",
                "end": "2026-07-12T00:30:00-07:00",
            },
            {
                "id": "all-day",
                "title": "All day",
                "start": "2026-07-14",
                "end": "2026-07-15",
                "all_day": True,
            },
            {
                "id": "ends-at-start",
                "title": "Previous week",
                "start": "2026-07-11T22:00:00-07:00",
                "end": "2026-07-12T00:00:00-07:00",
            },
            {
                "id": "next-week",
                "title": "Next week",
                "start": "2026-07-19",
                "end": "2026-07-20",
            },
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_calendar(root, events)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(
                server, "google_credentials", return_value=(None, "Google OAuth token not found")
            ):
                payload, status = server.calendar_request_payload(
                    "start=2026-07-12&days=7&timezone=America%2FLos_Angeles"
                )

        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in payload["items"]], ["overlap-start", "all-day"])
        self.assertEqual(payload["items"][1]["end"], "2026-07-15")
        self.assertTrue(payload["items"][1]["all_day"])
        self.assertEqual(payload["window"]["start"], "2026-07-12T00:00:00-07:00")
        self.assertEqual(payload["window"]["end"], "2026-07-19T00:00:00-07:00")
        self.assertEqual(payload["window"]["label"], "July 12–18, 2026")
        self.assertEqual(payload["timezone"]["id"], "America/Los_Angeles")
        self.assertEqual(payload["timezone"]["utc_offset"], "-07:00")
        self.assertTrue(payload["read_only"])

    def test_calendar_query_rejects_invalid_dates_ranges_timezones_and_duplicates(self):
        invalid_queries = (
            "start=2026-07-13&days=7",
            "start=07-12-2026&days=7",
            "start=2026-07-12&days=14",
            "days=7",
            "start=2026-07-12&days=7&timezone=..%2Fsecret",
            "start=2026-07-12&start=2026-07-19&days=7",
            "start=2026-07-12&days=7&calendar=other",
        )
        with patch.object(server, "google_calendar_events") as calendar_events:
            for query in invalid_queries:
                with self.subTest(query=query):
                    payload, status = server.calendar_request_payload(query)
                    self.assertEqual(status, 400)
                    self.assertIn("error", payload)
            calendar_events.assert_not_called()

    def test_google_exact_week_uses_primary_fixed_window_and_cache_is_window_scoped(self):
        calls = []
        response = {
            "items": [
                {
                    "id": "all-day",
                    "summary": "All day event",
                    "start": {"date": "2026-07-14"},
                    "end": {"date": "2026-07-16"},
                    "status": "confirmed",
                },
                {
                    "id": "outside",
                    "summary": "Bad provider spillover",
                    "start": {"dateTime": "2026-07-20T09:00:00-07:00"},
                    "end": {"dateTime": "2026-07-20T10:00:00-07:00"},
                },
            ]
        }
        service = FakeCalendarService(response, calls)
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_calendar(root, [])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(
                server, "google_credentials", return_value=(object(), None)
            ), patch("googleapiclient.discovery.build", return_value=service) as build:
                first = server.google_calendar_events(
                    start="2026-07-12", timezone_name="America/Los_Angeles"
                )
                cached = server.google_calendar_events(
                    start="2026-07-12", timezone_name="America/Los_Angeles"
                )
                other_week = server.google_calendar_events(
                    start="2026-07-19", timezone_name="America/Los_Angeles"
                )

        self.assertEqual(build.call_count, 2)
        self.assertFalse(first["cache"]["cached"])
        self.assertTrue(cached["cache"]["cached"])
        self.assertFalse(other_week["cache"]["cached"])
        self.assertEqual([item["id"] for item in first["items"]], ["all-day"])
        self.assertEqual(first["items"][0]["end"], "2026-07-16")
        self.assertTrue(first["items"][0]["all_day"])
        self.assertEqual(calls[0]["calendarId"], "primary")
        self.assertEqual(calls[0]["timeMin"], "2026-07-12T07:00:00Z")
        self.assertEqual(calls[0]["timeMax"], "2026-07-19T07:00:00Z")
        self.assertEqual(calls[0]["timeZone"], "America/Los_Angeles")
        self.assertTrue(calls[0]["singleEvents"])
        self.assertEqual(calls[0]["orderBy"], "startTime")

    def test_google_calendar_reads_a_second_page_with_provider_token(self):
        calls = []
        responses = [
            {
                "items": [
                    {
                        "id": "first",
                        "summary": "First page",
                        "start": {"dateTime": "2026-07-13T09:00:00-07:00"},
                        "end": {"dateTime": "2026-07-13T10:00:00-07:00"},
                    }
                ],
                "nextPageToken": "provider-page-2",
            },
            {
                "items": [
                    {
                        "id": "second",
                        "summary": "Second page",
                        "start": {"dateTime": "2026-07-14T11:00:00-07:00"},
                        "end": {"dateTime": "2026-07-14T12:00:00-07:00"},
                    }
                ]
            },
        ]
        service = PaginatedCalendarService(responses, calls)
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_calendar(root, [])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(
                server, "google_credentials", return_value=(object(), None)
            ), patch("googleapiclient.discovery.build", return_value=service):
                payload = server.google_calendar_events(
                    start="2026-07-12",
                    timezone_name="America/Los_Angeles",
                    refresh=True,
                )

        self.assertEqual([item["id"] for item in payload["items"]], ["first", "second"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("pageToken", calls[0])
        self.assertEqual(calls[1]["pageToken"], "provider-page-2")
        self.assertLessEqual(len(calls), server.CALENDAR_MAX_PAGES)
        self.assertLessEqual(payload["summary"]["count"], server.CALENDAR_MAX_EVENTS)

    def test_google_calendar_pagination_stops_at_page_and_result_bounds(self):
        page_calls = []
        responses = [
            {
                "items": [
                    {
                        "id": f"page-{index}",
                        "summary": f"Page {index}",
                        "start": {"date": "2026-07-14"},
                        "end": {"date": "2026-07-15"},
                    }
                ],
                "nextPageToken": f"token-{index + 1}",
            }
            for index in range(server.CALENDAR_MAX_PAGES + 1)
        ]
        service = PaginatedCalendarService(responses, page_calls)
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_calendar(root, [])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(
                server, "google_credentials", return_value=(object(), None)
            ), patch("googleapiclient.discovery.build", return_value=service):
                paged = server.google_calendar_events(
                    start="2026-07-12",
                    timezone_name="America/Los_Angeles",
                    refresh=True,
                )

        self.assertEqual(len(page_calls), server.CALENDAR_MAX_PAGES)
        self.assertEqual(len(paged["items"]), server.CALENDAR_MAX_PAGES)

        oversized_calls = []
        oversized = {
            "items": [
                {
                    "id": f"event-{index}",
                    "summary": f"Event {index}",
                    "start": {"date": "2026-07-14"},
                    "end": {"date": "2026-07-15"},
                }
                for index in range(75)
            ]
        }
        oversized_service = FakeCalendarService(oversized, oversized_calls)
        server.CALENDAR_CACHE.update({"key": None, "payload": None, "fetched_at": None})
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_calendar(root, [])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(
                server, "google_credentials", return_value=(object(), None)
            ), patch("googleapiclient.discovery.build", return_value=oversized_service):
                limited = server.google_calendar_events(
                    limit=50,
                    start="2026-07-12",
                    timezone_name="America/Los_Angeles",
                    refresh=True,
                )

        self.assertEqual(len(limited["items"]), 50)
        self.assertEqual(oversized_calls[0]["maxResults"], 50)

    def test_exact_week_endpoint_keeps_more_than_fifty_provider_events(self):
        calls = []
        response = {
            "items": [
                {
                    "id": f"event-{index}",
                    "summary": f"Appointment {index}",
                    "start": {"dateTime": "2026-07-14T09:00:00-07:00"},
                    "end": {"dateTime": "2026-07-14T09:30:00-07:00"},
                }
                for index in range(75)
            ]
        }
        service = FakeCalendarService(response, calls)
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_calendar(root, [])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(
                server, "google_credentials", return_value=(object(), None)
            ), patch("googleapiclient.discovery.build", return_value=service):
                payload, status = server.calendar_request_payload(
                    "start=2026-07-12&days=7&timezone=America%2FLos_Angeles"
                )

        self.assertEqual(status, 200)
        self.assertEqual(payload["summary"]["count"], 75)
        self.assertEqual(len(payload["items"]), 75)
        self.assertEqual(calls[0]["maxResults"], server.CALENDAR_MAX_EVENTS)

    def test_calendar_mutations_bind_visible_week_and_reject_disconnected_items(self):
        connected = {
            "source": "google",
            "auth": "connected",
            "items": [{"id": "event-1", "title": "Visible appointment"}],
        }
        with patch.object(server, "google_calendar_events", return_value=connected) as events:
            event = server.calendar_event_by_id(
                "event-1",
                week_start="2026-07-12",
                timezone_name="America/Los_Angeles",
            )

        self.assertEqual(event["id"], "event-1")
        events.assert_called_once_with(
            days=7,
            limit=server.CALENDAR_MAX_EVENTS,
            start="2026-07-12",
            timezone_name="America/Los_Angeles",
            refresh=True,
        )

        disconnected = {**connected, "source": "local", "auth": "not_connected"}
        with patch.object(server, "google_calendar_events", return_value=disconnected):
            self.assertIsNone(
                server.calendar_event_by_id(
                    "event-1",
                    week_start="2026-07-12",
                    timezone_name="America/Los_Angeles",
                )
            )

    def test_calendar_mutation_window_requires_valid_complete_pair(self):
        invalid_payloads = (
            {"week_start": "2026-07-12"},
            {"timezone": "America/Los_Angeles"},
            {"week_start": "2026-07-13", "timezone": "America/Los_Angeles"},
            {"week_start": "2026-07-12", "timezone": "../secret"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                week_start, timezone_name, error = server.calendar_mutation_window(payload)
                self.assertIsNone(week_start)
                self.assertIsNone(timezone_name)
                self.assertTrue(error)

        self.assertEqual(server.calendar_mutation_window({}), (None, None, None))

    def test_calendar_link_passes_visible_week_to_event_revalidation(self):
        event = {
            "id": "event-1",
            "title": "Visible appointment",
            "start": "2026-07-14T09:00:00-07:00",
            "end": "2026-07-14T10:00:00-07:00",
        }
        task = {"id": "task-1", "title": "Prepare", "calendar_links": []}
        with patch.object(server, "calendar_event_by_id", return_value=event) as event_lookup, patch.object(
            server, "task_record", return_value=task
        ), patch.object(server, "update_task", return_value=({"ok": True}, 200)) as update:
            payload, status = server.link_task_calendar_event(
                "task-1",
                {
                    "event_id": "event-1",
                    "week_start": "2026-07-12",
                    "timezone": "America/Los_Angeles",
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        event_lookup.assert_called_once_with(
            "event-1",
            week_start="2026-07-12",
            timezone_name="America/Los_Angeles",
        )
        self.assertEqual(update.call_args.args[1]["calendar_links"][0]["event_id"], "event-1")

    def test_no_argument_request_preserves_rolling_agenda_contract(self):
        with patch.object(server, "google_calendar_events", return_value={"window": {"label": "rolling"}}) as events:
            payload, status = server.calendar_request_payload("")

        self.assertEqual(status, 200)
        self.assertEqual(payload["window"]["label"], "rolling")
        events.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
