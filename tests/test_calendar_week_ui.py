from pathlib import Path
import json
import os
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")


class CalendarWeekUiTests(unittest.TestCase):
    def block(self, start: str, end: str) -> str:
        return APP[APP.index(start) : APP.index(end, APP.index(start))]

    def test_week_is_sunday_through_saturday_and_uses_exact_backend_window(self):
        start_block = self.block("function startOfCalendarWeek", "function calendarWeekStartDate")
        self.assertIn("date.getDate() - date.getDay()", start_block)
        self.assertIn("Array.from({ length: 7 }", APP)

        request_block = self.block("function calendarWeekRequestUrl", "function calendarItemKey")
        self.assertIn("start: calendarDateKey(weekStart)", request_block)
        self.assertIn("days: '7'", request_block)
        self.assertIn("params.set('timezone', timezone)", request_block)

    def test_week_renderer_separates_all_day_and_timed_events(self):
        render_block = self.block("function renderCalendarWeek(payload", "function renderCalendarWeekLoading")
        for hook in (
            "#calendar-week-days",
            "#calendar-all-day-events",
            "#calendar-time-labels",
            "#calendar-week-events",
            "#calendar-now-line",
        ):
            self.assertIn(hook, render_block)
        self.assertIn("calendarAllDayItemsByDay(items, weekStart)", render_block)
        self.assertIn("calendarTimedSegmentsByDay(items, weekStart)", render_block)
        self.assertIn("layoutCalendarDayOverlaps(segments)", render_block)
        self.assertIn("shell.setAttribute('aria-busy', 'false')", render_block)

    def test_overlap_columns_are_deterministic(self):
        overlap_block = self.block("function layoutCalendarDayOverlaps", "function calendarVisibleHours")
        self.assertIn("a.startMinute - b.startMinute", overlap_block)
        self.assertIn("a.endMinute - b.endMinute", overlap_block)
        self.assertIn("a.item._calendarKey.localeCompare", overlap_block)
        self.assertIn("entry.endMinute <= segment.startMinute", overlap_block)
        self.assertIn("columnCount", overlap_block)

    def test_fall_back_fold_keeps_real_duration_and_overlap_columns_at_runtime(self):
        script = r'''
const source = require('fs').readFileSync(process.argv[1], 'utf8');
function functionSource(name) {
  const marker = `function ${name}`;
  const start = source.indexOf(marker);
  if (start < 0) throw new Error(`missing ${name}`);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`unterminated ${name}`);
}
eval(functionSource('calendarTimedSegmentMetrics'));
eval(functionSource('layoutCalendarDayOverlaps'));
const day = new Date(2026, 10, 1, 0, 0, 0);
const nextDay = new Date(2026, 10, 2, 0, 0, 0);
const folded = calendarTimedSegmentMetrics(
  new Date('2026-11-01T01:30:00-07:00'),
  new Date('2026-11-01T01:30:00-08:00'),
  day,
  nextDay,
);
const unequalFold = calendarTimedSegmentMetrics(
  new Date('2026-11-01T01:15:00-07:00'),
  new Date('2026-11-01T01:45:00-08:00'),
  day,
  nextDay,
);
const spanningFold = calendarTimedSegmentMetrics(
  new Date('2026-11-01T00:30:00-07:00'),
  new Date('2026-11-01T01:30:00-08:00'),
  day,
  nextDay,
);
const normal = calendarTimedSegmentMetrics(
  new Date('2026-11-01T09:15:00-08:00'),
  new Date('2026-11-01T10:00:00-08:00'),
  day,
  nextDay,
);
const layout = layoutCalendarDayOverlaps([
  { item: { _calendarKey: 'folded' }, ...folded },
  { item: { _calendarKey: 'peer' }, startMinute: 105, endMinute: 135 },
]);
process.stdout.write(JSON.stringify({ folded, unequalFold, spanningFold, normal, layout }));
'''
        result = subprocess.run(
            ["node", "-e", script, str(ROOT / "public" / "app.js")],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "TZ": "America/Los_Angeles"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["folded"], {"startMinute": 90, "endMinute": 150})
        self.assertEqual(payload["unequalFold"], {"startMinute": 75, "endMinute": 165})
        self.assertEqual(payload["spanningFold"], {"startMinute": 30, "endMinute": 150})
        self.assertEqual(payload["normal"], {"startMinute": 555, "endMinute": 600})
        self.assertEqual([item["column"] for item in payload["layout"]], [0, 1])
        self.assertTrue(all(item["columnCount"] == 2 for item in payload["layout"]))

    def test_event_buttons_are_accessible_and_inspector_retains_safe_actions(self):
        button_block = self.block("function calendarWeekEventButton", "function renderCalendarEventInspector")
        self.assertIn('type="button"', button_block)
        self.assertIn("data-calendar-event-select", button_block)
        self.assertIn("aria-selected", button_block)
        self.assertIn("aria-pressed", button_block)
        self.assertIn("aria-label", button_block)

        inspector_block = self.block("function renderCalendarEventInspector", "function selectCalendarEvent")
        self.assertIn("safeExternalUrl(item.htmlLink || '')", inspector_block)
        self.assertIn('target="_blank" rel="noreferrer"', inspector_block)
        self.assertIn("data-calendar-week-start", inspector_block)
        self.assertIn("data-calendar-timezone", inspector_block)
        action_block = self.block("function calendarEventActionMarkup", "const CALENDAR_DEFAULT_START_HOUR")
        self.assertIn("data-calendar-create-task", action_block)
        self.assertIn("data-calendar-link-task", action_block)
        self.assertIn("data-calendar-linked-task", action_block)

        context_block = self.block("function calendarMutationContext", "function renderCalendarWeek")
        self.assertIn("week_start: weekStart, timezone", context_block)
        self.assertIn("calendarMutationContext(createFromCalendar)", APP)
        self.assertIn("calendarMutationContext(linkCalendar)", APP)
        self.assertGreaterEqual(CORE.count("if (context.week_start && context.timezone)"), 2)
        self.assertGreaterEqual(CORE.count("payload.week_start = context.week_start"), 2)
        self.assertGreaterEqual(CORE.count("payload.timezone = context.timezone"), 2)

    def test_mutation_controls_render_only_for_verified_google_payloads(self):
        script = r'''
const source = require('fs').readFileSync(process.argv[1], 'utf8');
function functionSource(name) {
  const marker = `function ${name}`;
  const start = source.indexOf(marker);
  const parameters = source.indexOf('(', start);
  let parameterDepth = 0;
  let brace = -1;
  for (let index = parameters; index < source.length; index += 1) {
    if (source[index] === '(') parameterDepth += 1;
    if (source[index] === ')') parameterDepth -= 1;
    if (parameterDepth === 0) {
      brace = source.indexOf('{', index);
      break;
    }
  }
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') depth -= 1;
    if (depth === 0) return source.slice(start, index + 1);
  }
  throw new Error(`unterminated ${name}`);
}
function escapeHtml(value = '') { return String(value); }
eval(functionSource('calendarPayloadIsVerified'));
eval(functionSource('calendarEventActionMarkup'));
const event = { id: 'event-1', title: 'Review' };
const payloads = {
  local: { source: 'local', auth: 'connected' },
  error: { source: 'local', auth: 'error' },
  disconnected: { source: 'local', auth: 'not_connected' },
  google: { source: 'google', auth: 'connected' },
};
const result = Object.fromEntries(Object.entries(payloads).map(([key, payload]) => [
  key,
  calendarEventActionMarkup(event, null, { verified: calendarPayloadIsVerified(payload) }),
]));
result.linkedLocal = calendarEventActionMarkup(event, { id: 'task-1' }, { verified: false });
process.stdout.write(JSON.stringify(result));
'''
        result = subprocess.run(
            ["node", "-e", script, str(ROOT / "public" / "app.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = json.loads(result.stdout)
        for source in ("local", "error", "disconnected"):
            self.assertEqual(rendered[source], "")
        self.assertIn("data-calendar-create-task", rendered["google"])
        self.assertIn("data-calendar-link-task", rendered["google"])
        self.assertIn("data-calendar-linked-task", rendered["linkedLocal"])

        week_items = self.block("function calendarWeekItems", "function calendarAllDayItemsByDay")
        self.assertIn("_calendarVerified: verified", week_items)
        inspector = self.block("function renderCalendarEventInspector", "function selectCalendarEvent")
        self.assertIn("item._calendarVerified ? safeExternalUrl", inspector)
        agenda = self.block("function renderCalendarInto", "function renderCalendar(payload")
        self.assertIn("const verified = calendarPayloadIsVerified(payload)", agenda)
        self.assertIn("calendarEventActionMarkup(item, linkedTask, { verified })", agenda)
        self.assertIn("verified ? calendarEventLink(item) : ''", agenda)

    def test_disconnected_preview_is_generic_and_cannot_mutate_tasks(self):
        preview_block = self.block("function calendarPreviewEvents", "function calendarWeekItems")
        for title in ("Weekly planning", "Project review", "Focus block"):
            self.assertIn(title, preview_block)
        self.assertIn("preview: true", preview_block)

        inspector_block = self.block("function renderCalendarEventInspector", "function selectCalendarEvent")
        self.assertIn("Preview events are client-only examples", inspector_block)
        action_block = self.block("function calendarEventActionMarkup", "const CALENDAR_DEFAULT_START_HOUR")
        self.assertIn("if (!verified || !item.id) return ''", action_block)

    def test_navigation_preserves_selected_week_and_rejects_stale_responses(self):
        load_block = self.block("async function loadCalendarWeek", "function navigateCalendarWeek")
        self.assertIn("state.calendarWeekRequestToken", load_block)
        self.assertIn("requestToken !== state.calendarWeekRequestToken", load_block)
        self.assertIn("state.calendarWeekStart !== weekKey", load_block)

        refresh_block = self.block("async function refresh()", "function queueMessageSearch")
        self.assertIn("calendarWeekRequestUrl(weekStart)", refresh_block)
        self.assertIn("state.calendarWeekStart === calendarRequestWeekKey", refresh_block)
        self.assertIn("requests.calendar = api(endpoints.calendar)", refresh_block)

    def test_today_compact_agenda_stays_separate_and_no_calendar_timer_is_added(self):
        render_block = self.block("function renderCalendar(payload", "function renderEmail")
        self.assertIn("if (view === 'calendar')", render_block)
        self.assertIn("renderCalendarInto('#calendar-list', payload, { limit: 5 })", render_block)
        calendar_feature = self.block("const CALENDAR_DEFAULT_START_HOUR", "function renderCalendarInto")
        self.assertNotIn("setInterval", calendar_feature)

    def test_removed_calendar_source_pills_have_no_dead_queries(self):
        self.assertNotIn("#calendar-source-pill", APP)
        self.assertNotIn("#calendar-full-source-pill", APP)
        self.assertNotIn("data-calendar-event-id", APP)
        self.assertNotIn("calendarWeekPayload", APP)
        self.assertNotIn("calendarWeekPreview", APP)

    def test_javascript_parses(self):
        result = subprocess.run(
            ["node", "--check", str(ROOT / "public" / "app.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
