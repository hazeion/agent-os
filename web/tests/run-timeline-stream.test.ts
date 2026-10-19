import assert from "node:assert/strict";
import test from "node:test";

import { BridgeRunEventsError, type PublicBridgeRunEvents } from "../src/lib/bridge-run-events.ts";
import { createRunTimelineStream } from "../src/lib/run-timeline-stream.ts";

const event = { id: "event_current", run_id: "run_current", sequence: 1, type: "run.started", occurred_at: "2026-08-22T00:01:00Z", summary: "Runtime accepted dispatch", message: null, metrics: {}, presentation: null };
const readText = (stream: ReadableStream<Uint8Array>) => new Response(stream).text();

test("revocation during a read prevents disclosure and releases the exact stream", async () => {
  let authorized = true, releases = 0;
  const result = await readText(createRunTimelineStream({ runId: "run_current", after: 0, signal: new AbortController().signal,
    authorize: async () => authorized, release: async () => { releases++; },
    read: async () => { authorized = false; return { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", run_id: "run_current", after: 0, next_cursor: 1, cursor_reset_required: false, events: [event] }; },
  }));
  assert.match(result, /owner-auth-required/);
  assert.doesNotMatch(result, /Runtime accepted|event_current|event: snapshot/);
  assert.equal(releases, 1);
});

test("an unverified lease cannot begin a protected read", async () => {
  let reads = 0, releases = 0;
  const result = await readText(createRunTimelineStream({ runId: "run_current", after: 0, signal: new AbortController().signal,
    authorize: async () => false, release: async () => { releases++; },
    read: async () => { reads++; throw new Error("should not run"); },
  }));
  assert.match(result, /owner-auth-required/);
  assert.equal(reads, 0); assert.equal(releases, 1);
});

test("timeline stream frames one initial snapshot, incremental events, keepalives, and reconnect retry", async () => {
  const responses: PublicBridgeRunEvents[] = [
    { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", run_id: "run_current", after: 0, next_cursor: 1, cursor_reset_required: false, events: [event] },
    { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", run_id: "run_current", after: 1, next_cursor: 1, cursor_reset_required: false, events: [] },
  ];
  const text = await readText(createRunTimelineStream({ runId: "run_current", after: 0, read: async () => responses.shift()!, signal: new AbortController().signal, polls: 2, pollMilliseconds: 0 }));
  assert.match(text, /^retry: 1500\n\n/);
  assert.match(text, /event: snapshot\nid: 1\ndata: \{"events":\[\{"id":"event_current"/);
  assert.match(text, /: keepalive\n\n/);
  assert.doesNotMatch(text, /content|runtime_run_ref/);
});

test("timeline stream frames explicit reset and fixed failure without private error detail", async () => {
  const reset: PublicBridgeRunEvents = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", run_id: "run_current", after: 7, next_cursor: 9, cursor_reset_required: true, events: [{ ...event, sequence: 9 }] };
  const resetText = await readText(createRunTimelineStream({ runId: "run_current", after: 7, read: async () => reset, signal: new AbortController().signal, polls: 1 }));
  assert.match(resetText, /event: snapshot\nid: 9/);
  assert.match(resetText, /"reset":true/);
  const failureText = await readText(createRunTimelineStream({ runId: "run_current", after: 0, read: async () => { throw new BridgeRunEventsError("bridge_unavailable"); }, signal: new AbortController().signal, polls: 1 }));
  assert.match(failureText, /event: error\nid: 0\ndata: \{"code":"bridge_unavailable"\}/);
  assert.doesNotMatch(failureText, /BridgeRunEventsError/);
});

test("timeline stream frames a later retention reset with the UI envelope", async () => {
  const snapshots: PublicBridgeRunEvents[] = [
    { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", run_id: "run_current", after: 0, next_cursor: 1, cursor_reset_required: false, events: [event] },
    { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", run_id: "run_current", after: 1, next_cursor: 9, cursor_reset_required: true, events: [{ ...event, sequence: 9 }] },
  ];
  const text = await readText(createRunTimelineStream({ runId: "run_current", after: 0, read: async () => snapshots.shift()!, signal: new AbortController().signal, polls: 2, pollMilliseconds: 0 }));
  assert.match(text, /event: reset\nid: 9\ndata: \{"events":\[\{"id":"event_current"[^\n]+"cursor":9,"reset":true\}/);
});
