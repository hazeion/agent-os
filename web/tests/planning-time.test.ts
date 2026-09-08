import assert from "node:assert/strict";
import test from "node:test";
import { inputTimestamp, localInputTimestamp, planningTimestamp } from "../src/lib/planning-time.ts";

test("planning time uses compatible Intl fields and readable zone context", () => {
  const text = planningTimestamp("2026-09-06T16:00:00.000000Z", "America/Los_Angeles", "en-US");
  assert.match(text, /Sep 6, 2026/u);
  assert.match(text, /9:00 AM/u);
  assert.match(text, /PDT|GMT-7/u);
  assert.doesNotMatch(text, /T16:00|000000/u);
  assert.match(planningTimestamp("2026-09-06T16:00:00Z", "invalid-zone", "en-US"), /UTC/u);
  assert.equal(planningTimestamp("not a timestamp"), "Time unavailable");
});

test("device-local reminder input preserves exact unchanged autumn folds and rejects spring gaps", () => {
  const originalZone = process.env.TZ;
  process.env.TZ = "America/Los_Angeles";
  try {
    const first = "2026-11-01T08:30:27.123456Z";
    const second = "2026-11-01T09:30:27.654321Z";
    assert.equal(inputTimestamp(first), "2026-11-01T01:30");
    assert.equal(inputTimestamp(second), "2026-11-01T01:30");
    assert.equal(localInputTimestamp("2026-11-01T01:30", first), first);
    assert.equal(localInputTimestamp("2026-11-01T01:30", second), second);
    process.env.TZ = "America/New_York";
    assert.equal(localInputTimestamp("2026-11-01T01:30", second, "2026-11-01T01:30"), second);
    process.env.TZ = "America/Los_Angeles";
    assert.equal(localInputTimestamp("2026-09-06T09:00"), "2026-09-06T16:00:00.000Z");
    assert.equal(localInputTimestamp("2026-03-08T02:30"), "");
    assert.equal(localInputTimestamp("2026-03-08T03:30"), "2026-03-08T10:30:00.000Z");
    assert.equal(localInputTimestamp("2026-02-30T09:00"), "");
    assert.equal(localInputTimestamp(""), "");
    assert.equal(localInputTimestamp("0000-01-01T09:00"), "");
  } finally {
    if (originalZone === undefined) delete process.env.TZ;
    else process.env.TZ = originalZone;
  }
});
