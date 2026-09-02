import type { PublicPlanningReminder } from "./public-planning.ts";

const SCHEDULE_STORAGE_KEY = "mentat.browser-task-reminders.v1";
const DELIVERY_STORAGE_KEY = "mentat.browser-task-reminder-deliveries.v1";
const MAXIMUM_TASKS = 512;
const MAXIMUM_DELIVERIES = 2_048;
const TASK_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;
const REMINDER_ID = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$/u;

type ScheduledReminder = { id: string; at: string };
type ScheduledTask = { task_id: string; title: string; reminders: ScheduledReminder[] };

function validText(value: unknown, maximum: number): value is string { return typeof value === "string" && !!value && value.trim() === value && [...value].length <= maximum && !/\p{C}/u.test(value); }
function validTimestamp(value: unknown): value is string { return typeof value === "string" && value.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/u.test(value) && !Number.isNaN(Date.parse(value)); }
function validScheduledReminder(value: unknown): value is ScheduledReminder { return !!value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === "at,id" && typeof (value as { id?: unknown }).id === "string" && REMINDER_ID.test((value as { id: string }).id) && validTimestamp((value as { at?: unknown }).at); }
function validScheduledTask(value: unknown): value is ScheduledTask {
  return !!value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === "reminders,task_id,title"
    && typeof (value as { task_id?: unknown }).task_id === "string" && TASK_ID.test((value as { task_id: string }).task_id)
    && validText((value as { title?: unknown }).title, 160)
    && Array.isArray((value as { reminders?: unknown }).reminders) && (value as { reminders: unknown[] }).reminders.length <= 20 && (value as { reminders: unknown[] }).reminders.every(validScheduledReminder)
    && new Set((value as { reminders: ScheduledReminder[] }).reminders.map((item) => item.id)).size === (value as { reminders: ScheduledReminder[] }).reminders.length;
}
function storage(): Storage | null { try { return window.localStorage; } catch { return null; } }
function schedule(): ScheduledTask[] {
  const source = storage(); if (!source) return [];
  try { const value: unknown = JSON.parse(source.getItem(SCHEDULE_STORAGE_KEY) ?? "[]"); return Array.isArray(value) && value.length <= MAXIMUM_TASKS && value.every(validScheduledTask) && new Set(value.map((item) => item.task_id)).size === value.length ? value : []; } catch { return []; }
}
function deliveries(): string[] {
  const source = storage(); if (!source) return [];
  try { const value: unknown = JSON.parse(source.getItem(DELIVERY_STORAGE_KEY) ?? "[]"); return Array.isArray(value) && value.length <= MAXIMUM_DELIVERIES && value.every((item) => typeof item === "string" && item.length <= 400 && !/\p{C}/u.test(item)) && new Set(value).size === value.length ? value : []; } catch { return []; }
}
function write(key: string, value: unknown) { try { storage()?.setItem(key, JSON.stringify(value)); } catch { /* Local reminder persistence is a best-effort browser convenience. */ } }
function deliveryKey(taskId: string, reminder: ScheduledReminder) { return JSON.stringify([taskId, reminder.id, reminder.at]); }

/** Mirror only the browser-owned schedule fields for a Task currently seen in the UI. */
export function syncBrowserTaskReminderSchedule(taskId: string, title: string, reminders: PublicPlanningReminder[]) {
  if (!TASK_ID.test(taskId) || !validText(title, 160) || !Array.isArray(reminders)) return;
  const entries: ScheduledReminder[] = [];
  for (const reminder of reminders) {
    if (!reminder.enabled || reminder.channel !== "browser" || reminder.notified_at !== undefined || !REMINDER_ID.test(reminder.id) || !validTimestamp(reminder.at)) continue;
    entries.push({ id: reminder.id, at: reminder.at });
  }
  if (entries.length > 20 || new Set(entries.map((item) => item.id)).size !== entries.length) return;
  const current = schedule().filter((item) => item.task_id !== taskId);
  if (entries.length) current.unshift({ task_id: taskId, title, reminders: entries });
  write(SCHEDULE_STORAGE_KEY, current.slice(0, MAXIMUM_TASKS));
}

/** Remove every locally-known schedule after a confirmed destructive planning mutation. */
export function clearBrowserTaskReminderSchedules() {
  try {
    const source = storage();
    source?.removeItem(SCHEDULE_STORAGE_KEY);
    source?.removeItem(DELIVERY_STORAGE_KEY);
  } catch { /* A later scheduler tick always re-reads storage and therefore fails closed. */ }
}

/** Deliver every due locally-scheduled occurrence at most once per browser profile. */
export function deliverDueBrowserTaskReminders(now: number = Date.now()): number {
  if (typeof Notification === "undefined" || Notification.permission !== "granted" || !Number.isFinite(now)) return 0;
  const delivered = deliveries(); const known = new Set(delivered); let count = 0;
  for (const task of schedule()) for (const reminder of task.reminders) {
    if (Date.parse(reminder.at) > now) continue;
    const key = deliveryKey(task.task_id, reminder);
    if (known.has(key)) continue;
    try { new Notification("Mentat reminder", { body: task.title, tag: `mentat-${task.task_id}-${reminder.id}` }); }
    catch { continue; }
    known.add(key); delivered.push(key); count += 1;
  }
  if (count) write(DELIVERY_STORAGE_KEY, delivered.slice(-MAXIMUM_DELIVERIES));
  return count;
}

/** Return a bounded delay until the next undelivered occurrence, or null when none exist. */
export function nextBrowserTaskReminderDelay(now: number = Date.now()): number | null {
  if (!Number.isFinite(now)) return null;
  const known = new Set(deliveries()); let next: number | null = null;
  for (const task of schedule()) for (const reminder of task.reminders) {
    if (known.has(deliveryKey(task.task_id, reminder))) continue;
    const at = Date.parse(reminder.at); if (Number.isNaN(at)) continue;
    next = next === null ? at : Math.min(next, at);
  }
  return next === null ? null : Math.max(0, Math.min(next - now, 2_147_000_000));
}
