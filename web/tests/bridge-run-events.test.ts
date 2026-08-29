import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { BridgeRunEventsError, fetchBridgeRunEvents, lastEventCursor, refreshBridgeRun } from "../src/lib/bridge-run-events.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars" };
const event = { id: "event_current", run_id: "run_current", sequence: 4, type: "run.started", occurred_at: "2026-08-22T00:01:00Z", summary: "Runtime accepted dispatch", message: null, metrics: { total_tokens: 12 }, presentation: null };
const payload = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", run_id: "run_current", after: 3, next_cursor: 4, cursor_reset_required: false, events: [event] };
function trustedVercelMessageId(runId: string) {
  const source = `vercel_message_${createHash("sha256").update(`${runId}:message`, "utf8").digest("hex").slice(0, 24)}`;
  return `event_${createHash("sha256").update(`${runId}:${source}`, "utf8").digest("hex").slice(0, 24)}`;
}

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

test("Run event bridge returns only a bounded message on message events", async () => {
  const resultEvent = {
    ...event,
    id: trustedVercelMessageId("run_current"),
    message: "A bounded result from Vercel.",
    sequence: 5,
    summary: "Vercel AI Gateway returned a response",
    type: "message",
  };
  const resultPayload = { ...payload, events: [event, resultEvent], next_cursor: 5 };
  const result = await fetchBridgeRunEvents(
    "run_current",
    3,
    async () => Response.json(resultPayload),
    environment,
  );
  assert.equal(result.events[1].message, "A bounded result from Vercel.");
  await assert.rejects(
    fetchBridgeRunEvents(
      "run_current",
      3,
      async () => Response.json({
        ...resultPayload,
        events: [event, { ...resultEvent, id: "event_result" }],
      }),
      environment,
    ),
    BridgeRunEventsError,
  );
  await assert.rejects(
    fetchBridgeRunEvents(
      "run_current",
      3,
      async () => Response.json({ ...payload, events: [{ ...event, message: "not allowed" }] }),
      environment,
    ),
    BridgeRunEventsError,
  );
  await assert.rejects(
    fetchBridgeRunEvents(
      "run_current",
      3,
      async () => Response.json({
        ...payload,
        events: [
          event,
          resultEvent,
          {
            ...resultEvent,
            id: "event_result_duplicate",
            sequence: 6,
            message: "A second result must fail closed.",
          },
        ],
        next_cursor: 6,
      }),
      environment,
    ),
    BridgeRunEventsError,
  );
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

test("Run event bridge accepts only fixed provenance-safe presentation labels", async () => {
  const tool = { ...event, id: "event_tool", metrics: {}, presentation: { kind: "tool", label: "Tool activity started", phase: "started" }, sequence: 5, summary: "Tool activity started", type: "tool.requested" };
  const reasoning = { ...event, id: "event_reasoning", metrics: {}, presentation: { kind: "reasoning", label: "Reasoning summary available", phase: "available" }, sequence: 6, summary: "Reasoning summary available", type: "message" };
  const safe = { ...payload, events: [event, tool, reasoning], next_cursor: 6 };
  assert.equal((await fetchBridgeRunEvents("run_current", 3, async () => Response.json(safe), environment)).events[2].presentation?.kind, "reasoning");
  for (const poisoned of [
    { ...tool, presentation: null },
    { ...tool, presentation: { ...tool.presentation, tool: "shell" } },
    { ...tool, presentation: { ...tool.presentation, label: "Using secret path" } },
    { ...reasoning, presentation: { ...reasoning.presentation, raw: "chain of thought" } },
  ]) {
    await assert.rejects(fetchBridgeRunEvents("run_current", 3, async () => Response.json({ ...payload, events: [poisoned], next_cursor: poisoned.sequence }), environment), BridgeRunEventsError);
  }
});

test("selected Run refresh is one exact private mutation", async () => {
  let call: { body: string | undefined; method: string | undefined; url: string } | null = null;
  const refreshed = await refreshBridgeRun("run_current", async (input, init) => {
    call = { body: init?.body?.toString(), method: init?.method, url: input.toString() };
    return Response.json({
      disposition: "reconciled",
      run_id: "run_current",
      runtime: "python",
      schema_version: 1,
      service: "mentat-local-bridge",
      status: "ready",
    });
  }, environment);
  assert.equal(refreshed.disposition, "reconciled");
  assert.deepEqual(call, {
    body: "{}",
    method: "POST",
    url: "http://127.0.0.1:49152/bridge/v1/runs/run_current/refresh",
  });
  await assert.rejects(
    refreshBridgeRun("run_current", async () => Response.json({
      disposition: "reconciled",
      run_id: "run_other",
      runtime: "python",
      schema_version: 1,
      service: "mentat-local-bridge",
      status: "ready",
    }), environment),
    BridgeRunEventsError,
  );
});

test("SSE reconnect headers accept only an exact bounded cursor", () => {
  assert.equal(lastEventCursor(null), 0);
  assert.equal(lastEventCursor("0"), 0);
  assert.equal(lastEventCursor("1000000000"), 1_000_000_000);
  for (const value of ["-1", "01x", "10000000000", "1, 2", " 1", "1 "]) assert.equal(lastEventCursor(value), null);
});
