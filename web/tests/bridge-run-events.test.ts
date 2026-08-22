import assert from "node:assert/strict";
import test from "node:test";

import { BridgeRunEventsError, fetchBridgeRunEvents, lastEventCursor } from "../src/lib/bridge-run-events.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars" };
const event = { id: "event_current", run_id: "run_current", sequence: 4, type: "run.started", occurred_at: "2026-08-22T00:01:00Z", summary: "Runtime accepted dispatch", metrics: { total_tokens: 12 } };
const payload = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", run_id: "run_current", after: 3, next_cursor: 4, cursor_reset_required: false, events: [event] };

test("Run event bridge uses one fixed path and rejects private or discontinuous events", async () => {
  let url = "";
  await assert.rejects(fetchBridgeRunEvents("run_current", 3, async (input) => { url = input.toString(); return Response.json({ ...payload, events: [{ ...event, content: "private" }] }); }, environment), BridgeRunEventsError);
  assert.equal(url, "http://127.0.0.1:49152/bridge/v1/runs/run_current/events?after=3");
  await assert.rejects(fetchBridgeRunEvents("run_current", 3, async () => Response.json({ ...payload, next_cursor: 5 }), environment), BridgeRunEventsError);
});

test("Run event bridge returns a copied bounded projection and maps fixed failures", async () => {
  const result = await fetchBridgeRunEvents("run_current", 3, async () => Response.json(payload), environment);
  assert.deepEqual(result, payload); assert.notEqual(result.events[0], event); assert.notEqual(result.events[0].metrics, event.metrics);
  const reset = { ...payload, after: 0, next_cursor: 4, cursor_reset_required: true };
  assert.equal((await fetchBridgeRunEvents("run_current", 0, async () => Response.json(reset), environment)).cursor_reset_required, true);
  const unavailable = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "unavailable" };
  await assert.rejects(fetchBridgeRunEvents("run_current", 0, async () => Response.json(unavailable, { status: 503 }), environment), (error: unknown) => error instanceof BridgeRunEventsError && error.code === "bridge_unavailable");
  await assert.rejects(fetchBridgeRunEvents("run_current", 0, async () => Response.json({ ...reset, events: Array.from({ length: 101 }, () => event) }), environment), BridgeRunEventsError);
  await assert.rejects(fetchBridgeRunEvents("run_invalid!", 0, async () => Response.json(payload), environment), (error: unknown) => error instanceof BridgeRunEventsError && error.code === "request_invalid");
});

test("Run event bridge encodes a valid colon-containing Run ID once", async () => {
  const runId = "run_current:child";
  const childEvent = { ...event, run_id: runId };
  const childPayload = { ...payload, run_id: runId, events: [childEvent] };
  let url = "";
  const result = await fetchBridgeRunEvents(runId, 3, async (input) => {
    url = input.toString();
    return Response.json(childPayload);
  }, environment);
  assert.equal(url, "http://127.0.0.1:49152/bridge/v1/runs/run_current%3Achild/events?after=3");
  assert.equal(result.run_id, runId);
});

test("SSE reconnect headers accept only an exact bounded cursor", () => {
  assert.equal(lastEventCursor(null), 0);
  assert.equal(lastEventCursor("0"), 0);
  assert.equal(lastEventCursor("1000000000"), 1_000_000_000);
  for (const value of ["-1", "01x", "10000000000", "1, 2", " 1", "1 "]) assert.equal(lastEventCursor(value), null);
});
