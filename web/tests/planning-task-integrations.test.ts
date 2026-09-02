import assert from "node:assert/strict";
import test from "node:test";

import {
  attachBridgePlanningTaskNote,
  fetchBridgePlanningCalendarWindow,
  fetchBridgePlanningNotePicker,
  linkBridgePlanningTaskCalendarEvent,
  replaceBridgePlanningTaskReminders,
} from "../src/lib/bridge-planning.ts";
import { createPlanningCalendarHandler, createPlanningNotePickerHandler, createPlanningTaskIntegrationHandler } from "../src/lib/planning-task-integrations-route.ts";
import {
  attachPlanningTaskNote,
  parsePlanningCalendarWindow,
  parsePlanningNotePicker,
  parsePlanningTaskIntegrationMutation,
  replacePlanningTaskReminders,
  PublicPlanningError,
} from "../src/lib/public-planning.ts";

const envelope = { runtime: "python" as const, schema_version: 1 as const, service: "mentat-local-bridge" as const, status: "ready" as const };
const project = { id: "project_alpha", name: "Alpha", revision: 1, status: "active" as const };
const task = { assigned_agent_id: null, attention_reasons: [], blocked: false, calendar_links: [], deferred: false, description: "Bounded Task", due_date: null, estimated_minutes: null, id: "task_alpha", needs_attention: false, note_links: [], planned_for_today: false, planning_state: "inbox" as const, priority: "medium" as const, project_id: project.id, project_name: project.name, recurrence: null, reminders: [], review_required: false, revision: 2, scheduled_block: null, status: "todo" as const, subtasks: [], tags: [], title: "Plan Alpha", updated_at: "2026-09-02T12:00:00Z", workflow_stage: "inbox" as const };
const integration = { ...envelope, action: "replace_reminders" as const, project, task };
const picker = { ...envelope, available: true, count: 1, notes: [{ path: "Plans/Alpha.md", title: "Alpha" }], query: "Alpha", truncated: false };
const calendar = { ...envelope, calendar_id: "primary" as const, event_count: 1, events: [{ all_day: false, end: "2026-09-08T21:00:00Z", id: "event_alpha", start: "2026-09-08T20:00:00Z", title: "Focus" }], label: "September 6–12, 2026", read_only: true as const, timezone: "America/Los_Angeles", week_end: "2026-09-13", week_start: "2026-09-06" };
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const headers = { Host: "127.0.0.1:8890", Origin: "http://127.0.0.1:8890", "Sec-Fetch-Site": "same-origin" };
const context = { params: Promise.resolve({ taskId: task.id }) };
const json = (value: unknown, status = 200) => Response.json(value, { headers: { "content-type": "application/json" }, status });
const post = (path: string, value: unknown) => new Request(`http://127.0.0.1:8890${path}`, { body: JSON.stringify(value), headers: { ...headers, "Content-Type": "application/json" }, method: "POST" });

test("integration projections remain bounded and exact", () => {
  assert.deepEqual(parsePlanningTaskIntegrationMutation(integration, task.id), integration);
  assert.deepEqual(parsePlanningNotePicker(picker, "Alpha"), picker);
  assert.deepEqual(parsePlanningCalendarWindow(calendar, "2026-09-06", "America/Los_Angeles"), calendar);
  for (const hostile of [
    { ...integration, runtime_reference: "private" },
    { ...picker, notes: [{ ...picker.notes[0], path: "C:/private.md" }] },
    { ...calendar, read_only: false },
    { ...calendar, events: [{ ...calendar.events[0], title: "private", raw: "secret" }] },
  ]) assert.throws(() => "action" in hostile ? parsePlanningTaskIntegrationMutation(hostile, task.id) : "notes" in hostile ? parsePlanningNotePicker(hostile, "Alpha") : parsePlanningCalendarWindow(hostile, "2026-09-06", "America/Los_Angeles"), PublicPlanningError);
});

test("integration bridge binds fixed paths and does not send browser delivery state", async () => {
  const calls: Array<{ body: unknown; path: string }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(input.toString());
    calls.push({ body: init?.body ? JSON.parse(String(init.body)) : null, path: `${url.pathname}${url.search}` });
    if (url.pathname.endsWith("planning-note-picker")) return json(picker);
    if (url.pathname.endsWith("planning-calendar")) return json(calendar);
    return json(integration);
  };
  await fetchBridgePlanningNotePicker("Alpha", fetcher, environment);
  await fetchBridgePlanningCalendarWindow("2026-09-06", "America/Los_Angeles", fetcher, environment);
  await replaceBridgePlanningTaskReminders(task.id, 1, [{ at: "2026-09-03T16:00:00Z", enabled: true, id: "reminder_alpha", timezone: "America/Los_Angeles" }], fetcher, environment);
  const attached = { ...integration, action: "attach_note" as const };
  await attachBridgePlanningTaskNote(task.id, 2, "Plans/Alpha.md", async (input, init) => { const url = new URL(input.toString()); calls.push({ body: JSON.parse(String(init?.body)), path: url.pathname }); return json(attached); }, environment);
  const linked = { ...integration, action: "calendar_link" as const };
  await linkBridgePlanningTaskCalendarEvent(task.id, 2, "event_alpha", "2026-09-06", "America/Los_Angeles", async (input, init) => { const url = new URL(input.toString()); calls.push({ body: JSON.parse(String(init?.body)), path: url.pathname }); return json(linked); }, environment);
  assert.deepEqual(calls, [
    { body: null, path: "/bridge/v1/agent-console/planning-note-picker?q=Alpha" },
    { body: null, path: "/bridge/v1/agent-console/planning-calendar?week_start=2026-09-06&timezone=America%2FLos_Angeles" },
    { body: { expected_revision: 1, reminders: [{ at: "2026-09-03T16:00:00Z", enabled: true, id: "reminder_alpha", timezone: "America/Los_Angeles" }] }, path: "/bridge/v1/planning/tasks/task_alpha/integrations/reminders" },
    { body: { expected_revision: 2, path: "Plans/Alpha.md" }, path: "/bridge/v1/planning/tasks/task_alpha/integrations/notes/attach" },
    { body: { event_id: "event_alpha", expected_revision: 2, timezone: "America/Los_Angeles", week_start: "2026-09-06" }, path: "/bridge/v1/planning/tasks/task_alpha/integrations/calendar/link" },
  ]);
});

test("same-origin integration routes enforce exact bodies and public clients use only named endpoints", async () => {
  const reminderHandler = createPlanningTaskIntegrationHandler("reminders", { gatewayPort: "8890", mutate: async () => integration });
  const noteHandler = createPlanningTaskIntegrationHandler("notes/attach", { gatewayPort: "8890", mutate: async () => ({ ...integration, action: "attach_note" }) });
  const pickerHandler = createPlanningNotePickerHandler({ gatewayPort: "8890", read: async () => picker });
  const calendarHandler = createPlanningCalendarHandler({ gatewayPort: "8890", read: async () => calendar });
  assert.equal((await reminderHandler(post(`/api/planning/tasks/${task.id}/integrations/reminders`, { expected_revision: 1, reminders: [] }), context)).status, 200);
  assert.equal((await reminderHandler(post(`/api/planning/tasks/${task.id}/integrations/reminders`, { expected_revision: 1, reminders: [], notified_at: "no" }), context)).status, 400);
  assert.equal((await noteHandler(post(`/api/planning/tasks/${task.id}/integrations/notes/attach`, { expected_revision: 1, path: "Plans/Alpha.md" }), context)).status, 200);
  assert.equal((await noteHandler(post(`/api/planning/tasks/${task.id}/integrations/notes/attach`, { expected_revision: 1, path: "../Alpha.md" }), context)).status, 400);
  assert.equal((await pickerHandler(new Request("http://127.0.0.1:8890/api/agent-console/planning-note-picker?q=Alpha", { headers }))).status, 200);
  assert.equal((await calendarHandler(new Request("http://127.0.0.1:8890/api/agent-console/planning-calendar?week_start=2026-09-06&timezone=America%2FLos_Angeles", { headers }))).status, 200);
  assert.equal((await calendarHandler(new Request("http://127.0.0.1:8890/api/agent-console/planning-calendar?week_start=2026-09-07&timezone=America%2FLos_Angeles", { headers }))).status, 400);
  const original = globalThis.fetch; const calls: string[] = [];
  globalThis.fetch = async (input) => { const url = new URL(input.toString(), "http://127.0.0.1:8890"); calls.push(url.pathname); return json(url.pathname.endsWith("notes/attach") ? { ...integration, action: "attach_note" } : integration); };
  try {
    await replacePlanningTaskReminders(task.id, 1, []);
    await attachPlanningTaskNote(task.id, 2, "Plans/Alpha.md");
    assert.deepEqual(calls, [`/api/planning/tasks/${task.id}/integrations/reminders`, `/api/planning/tasks/${task.id}/integrations/notes/attach`]);
  } finally { globalThis.fetch = original; }
});
