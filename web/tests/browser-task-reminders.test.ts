import assert from "node:assert/strict";
import test from "node:test";

import { clearBrowserTaskReminderSchedules, deliverDueBrowserTaskReminders, nextBrowserTaskReminderDelay, syncBrowserTaskReminderSchedule } from "../src/lib/browser-task-reminders.ts";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, value); },
  };
}

test("browser reminder delivery is permission-gated, occurrence-idempotent, and never writes delivery state back to a Task", () => {
  const originalWindow = globalThis.window; const originalNotification = globalThis.Notification;
  const localStorage = memoryStorage(); const delivered: Array<{ body: string; title: string }> = [];
  class BrowserNotification {
    static permission: NotificationPermission = "default";
    constructor(title: string, options?: NotificationOptions) { delivered.push({ body: options?.body ?? "", title }); }
  }
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage } });
  Object.defineProperty(globalThis, "Notification", { configurable: true, value: BrowserNotification });
  try {
    const reminders = [{ at: "2026-09-02T12:00:00Z", channel: "browser" as const, enabled: true, id: "reminder_alpha" }];
    syncBrowserTaskReminderSchedule("task_alpha", "Plan Alpha", reminders);
    assert.equal(deliverDueBrowserTaskReminders(Date.parse("2026-09-02T12:01:00Z")), 0);
    assert.deepEqual(delivered, []);
    BrowserNotification.permission = "granted";
    assert.equal(deliverDueBrowserTaskReminders(Date.parse("2026-09-02T12:01:00Z")), 1);
    assert.deepEqual(delivered, [{ body: "Plan Alpha", title: "Mentat reminder" }]);
    assert.equal(deliverDueBrowserTaskReminders(Date.parse("2026-09-02T12:02:00Z")), 0);
    assert.equal(nextBrowserTaskReminderDelay(Date.parse("2026-09-02T12:02:00Z")), null);
    syncBrowserTaskReminderSchedule("task_beta", "Plan Beta", [{ at: "2026-09-03T12:00:00Z", channel: "browser", enabled: true, id: "reminder_beta" }]);
    assert.equal(nextBrowserTaskReminderDelay(Date.parse("2026-09-02T12:02:00Z")), Date.parse("2026-09-03T12:00:00Z") - Date.parse("2026-09-02T12:02:00Z"));
    clearBrowserTaskReminderSchedules();
    assert.equal(nextBrowserTaskReminderDelay(Date.parse("2026-09-02T12:02:00Z")), null);
    assert.equal(deliverDueBrowserTaskReminders(Date.parse("2026-09-04T12:00:00Z")), 0);
  } finally {
    Object.defineProperty(globalThis, "window", { configurable: true, value: originalWindow });
    Object.defineProperty(globalThis, "Notification", { configurable: true, value: originalNotification });
  }
});
