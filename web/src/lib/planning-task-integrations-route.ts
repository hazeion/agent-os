import {
  attachBridgePlanningTaskNote,
  detachBridgePlanningTaskNote,
  fetchBridgePlanningCalendarWindow,
  fetchBridgePlanningNotePicker,
  linkBridgePlanningTaskCalendarEvent,
  replaceBridgePlanningTaskReminders,
  unlinkBridgePlanningTaskCalendarEvent,
} from "./bridge-planning.ts";
import { PLANNING_HEADERS, planningFailure, planningFixed, planningRequestAllowed } from "./planning-overview-route.ts";
import type { PublicPlanningCalendarWindow, PublicPlanningNotePicker, PublicPlanningReminder, PublicPlanningTaskIntegrationMutation } from "./public-planning.ts";

type Params = { params: Promise<{ taskId: string }> };
type IntegrationAction = "reminders" | "notes/attach" | "notes/detach" | "calendar/link" | "calendar/unlink";
const TASK = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const PATH = /^(?![~/])(?!(?:[A-Za-z]:|file:|obsidian:))/iu;
const TIMEZONE = /^[A-Za-z_+-]+(?:\/[A-Za-z_+-]+)*$/u;

function exact(value: Record<string, unknown>, fields: readonly string[]) { return Object.keys(value).sort().join(",") === [...fields].sort().join(","); }
function positive(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 1; }
function timestamp(value: unknown): value is string { return typeof value === "string" && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) && !Number.isNaN(Date.parse(value)); }
function date(value: unknown): value is string { if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false; const parsed = new Date(`${value}T00:00:00Z`); return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value; }
function timezone(value: unknown): value is string { return typeof value === "string" && value.length <= 64 && TIMEZONE.test(value); }
function sunday(value: string) { return date(value) && new Date(`${value}T00:00:00Z`).getUTCDay() === 0; }
function notePath(value: unknown): value is string { return typeof value === "string" && !!value && value.trim() === value && [...value].length <= 500 && !/[\\\p{C}]/u.test(value) && PATH.test(value) && value.toLowerCase().endsWith(".md") && value.split("/").every((part) => !!part && part !== "." && part !== ".."); }
function reminder(value: unknown): value is Omit<PublicPlanningReminder, "channel" | "notified_at"> { return !!value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).every((key) => new Set(["id", "at", "enabled", "timezone"]).has(key)) && typeof (value as { id?: unknown }).id === "string" && TASK.test((value as { id: string }).id) && timestamp((value as { at?: unknown }).at) && typeof (value as { enabled?: unknown }).enabled === "boolean" && ((value as { timezone?: unknown }).timezone === undefined || timezone((value as { timezone: unknown }).timezone)); }
async function body(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const length = request.headers.get("content-length"); if (length && (!/^\d{1,6}$/u.test(length) || Number(length) > 16_384)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const part = await reader.read(); if (part.done) break; size += part.value.byteLength; if (size > 16_384) { await reader.cancel(); return null; } chunks.push(part.value); } } catch { await reader.cancel().catch(() => undefined); return null; } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null; } catch { return null; }
}
async function taskId(context: Params) { const { taskId: value } = await context.params; return TASK.test(value) ? value : null; }

type Mutation = (taskId: string, expectedRevision: number, ...args: never[]) => Promise<PublicPlanningTaskIntegrationMutation>;

export function createPlanningNotePickerHandler({ read = fetchBridgePlanningNotePicker, gatewayPort = process.env.PORT }: Readonly<{ read?: (query?: string) => Promise<PublicPlanningNotePicker>; gatewayPort?: string }> = {}) {
  return async (request: Request) => {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    const entries = [...new URL(request.url).searchParams.entries()];
    if (entries.length > 1 || entries.length === 1 && (entries[0]![0] !== "q" || entries[0]![1].trim() !== entries[0]![1] || [...entries[0]![1]].length > 120 || /\p{C}/u.test(entries[0]![1]))) return planningFixed("invalid", 400);
    try { return Response.json(await read(entries[0]?.[1] ?? ""), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}

export function createPlanningCalendarHandler({ read = fetchBridgePlanningCalendarWindow, gatewayPort = process.env.PORT }: Readonly<{ read?: (weekStart: string, timezoneName: string) => Promise<PublicPlanningCalendarWindow>; gatewayPort?: string }> = {}) {
  return async (request: Request) => {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    const entries = [...new URL(request.url).searchParams.entries()]; const values = Object.fromEntries(entries);
    if (entries.length !== 2 || Object.keys(values).length !== 2 || !exact(values, ["week_start", "timezone"]) || !sunday(values.week_start) || !timezone(values.timezone)) return planningFixed("invalid", 400);
    try { return Response.json(await read(values.week_start, values.timezone), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}

function validMutation(action: IntegrationAction, value: Record<string, unknown>) {
  if (!positive(value.expected_revision)) return false;
  if (action === "reminders") return exact(value, ["expected_revision", "reminders"]) && Array.isArray(value.reminders) && value.reminders.length <= 20 && value.reminders.every(reminder) && new Set(value.reminders.map((item) => item.id)).size === value.reminders.length;
  if (action === "notes/attach" || action === "notes/detach") return exact(value, ["expected_revision", "path"]) && notePath(value.path);
  if (action === "calendar/link") return exact(value, ["event_id", "expected_revision", "timezone", "week_start"]) && typeof value.event_id === "string" && TASK.test(value.event_id) && typeof value.week_start === "string" && sunday(value.week_start) && timezone(value.timezone);
  return exact(value, ["calendar_id", "event_id", "expected_revision"]) && value.calendar_id === "primary" && typeof value.event_id === "string" && TASK.test(value.event_id);
}

export function createPlanningTaskIntegrationHandler(action: IntegrationAction, { mutate, gatewayPort = process.env.PORT }: Readonly<{ mutate?: Mutation; gatewayPort?: string }> = {}) {
  const operation = mutate ?? (action === "reminders" ? replaceBridgePlanningTaskReminders : action === "notes/attach" ? attachBridgePlanningTaskNote : action === "notes/detach" ? detachBridgePlanningTaskNote : action === "calendar/link" ? linkBridgePlanningTaskCalendarEvent : unlinkBridgePlanningTaskCalendarEvent) as Mutation;
  return async (request: Request, context: Params) => {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400);
    const id = await taskId(context); const value = await body(request);
    if (!id || !value || !validMutation(action, value)) return planningFixed("invalid", 400);
    try {
      const result = action === "reminders"
        ? await (operation as typeof replaceBridgePlanningTaskReminders)(id, value.expected_revision as number, value.reminders as Array<Omit<PublicPlanningReminder, "channel" | "notified_at">>)
        : action === "notes/attach" || action === "notes/detach"
          ? await (operation as typeof attachBridgePlanningTaskNote)(id, value.expected_revision as number, value.path as string)
          : action === "calendar/link"
            ? await (operation as typeof linkBridgePlanningTaskCalendarEvent)(id, value.expected_revision as number, value.event_id as string, value.week_start as string, value.timezone as string)
            : await (operation as typeof unlinkBridgePlanningTaskCalendarEvent)(id, value.expected_revision as number, "primary", value.event_id as string);
      return Response.json(result, { headers: PLANNING_HEADERS });
    } catch (error) { return planningFailure(error); }
  };
}
