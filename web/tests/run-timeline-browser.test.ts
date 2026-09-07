import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { JSDOM } from "jsdom";
import { fetchBridgeRunEvents } from "../src/lib/bridge-run-events.ts";
import { createRunTimelineStream } from "../src/lib/run-timeline-stream.ts";

const runtime = readFileSync(new URL("../public/shell-runtime.js", import.meta.url), "utf8");
// Python tests regenerate these exact projections from canonical SQLite Runs.
const fixtures = JSON.parse(readFileSync(new URL("../../tests/fixtures/run_timeline_contract.json", import.meta.url), "utf8"));
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A".repeat(48) };

function browser() {
  const dom = new JSDOM('<!doctype html><html><body><article id="card"><button id="open">Open timeline</button></article></body></html>', {
    url: "http://127.0.0.1:8888/runs", runScripts: "outside-only",
  });
  const { window } = dom;
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;
  window.requestAnimationFrame = () => 0;
  class TimelineSource extends window.EventTarget {
    static CONNECTING = 0;
    closed = false;
    readyState = 1;
    close() { this.closed = true; }
  }
  const sources: TimelineSource[] = [];
  Object.assign(window, { EventSource: class extends TimelineSource { constructor() { super(); sources.push(this); } } });
  window.eval(runtime);
  window.eval('openRunTimeline({ id: "run_timeline_contract" }, document.getElementById("card"), document.getElementById("open"))');
  const source = sources[0];
  return {
    dom, window,
    get source() { return source; },
    send(type: string, value: unknown) { source.dispatchEvent(new window.MessageEvent(type, { data: JSON.stringify(value) })); },
    rows: () => window.document.querySelectorAll("[data-run-event-sequence]"),
    notice: () => window.document.querySelector("[data-run-timeline-notice]")?.textContent,
  };
}

test("canonical accepted and failed Codex events survive Node, SSE and the Runs browser", async () => {
  for (const fixture of fixtures) {
    const page = browser();
    try {
      const payload = await fetchBridgeRunEvents(fixture.run_id, 0, async () => Response.json(fixture), environment);
      const stream = createRunTimelineStream({ runId: payload.run_id, after: 0, read: async () => payload, signal: new AbortController().signal, polls: 1 });
      const text = await new Response(stream).text();
      const data = text.split("\n").find((line) => line.startsWith("data: "));
      assert.ok(data);
      page.send("snapshot", JSON.parse(data.slice(6)));
      assert.equal(page.rows().length, fixture.events.length);
      assert.equal(page.source.closed, false);
      assert.equal(page.notice(), "Watching live events.");
      for (const event of fixture.events) assert.ok(page.window.document.body.textContent?.includes(event.summary));
      // A reconnect merges retained evidence, then an explicit reset replaces it.
      page.send("snapshot", { events: [], cursor: payload.next_cursor, reset: false });
      assert.equal(page.rows().length, fixture.events.length);
      page.send("reset", { events: [fixture.events.at(-1)], cursor: payload.next_cursor, reset: true });
      assert.equal(page.rows().length, 1);
    } finally { page.dom.window.close(); }
  }
});

test("Runs accepts only the exact safe presentation classes and keeps text inert", () => {
  const base = fixtures[0].events[0];
  for (const [type, presentation] of [
    ["tool.requested", { kind: "tool", phase: "requested", label: "Tool activity requested" }],
    ["tool.requested", { kind: "tool", phase: "started", label: "Tool activity started" }],
    ["tool.completed", { kind: "tool", phase: "completed", label: "Tool activity completed" }],
    ["message", { kind: "reasoning", phase: "available", label: "Reasoning summary available" }],
  ] as const) {
    const page = browser();
    try {
      page.send("timeline", { event: { ...base, type, presentation, summary: presentation.label } });
      assert.equal(page.rows().length, 1);
      assert.equal(page.source.closed, false);
    } finally { page.dom.window.close(); }
  }
  for (const event of [
    { ...base, presentation: undefined },
    { ...base, presentation: { kind: "reasoning", phase: "available", label: "Reasoning summary available" } },
    { ...base, type: "tool.requested", presentation: null },
    { ...base, type: "message", summary: "Reasoning summary available", presentation: { kind: "reasoning", phase: "available", label: "Reasoning summary available", raw: "private" } },
    { ...base, runtime_run_ref: "private" },
    { ...base, run_id: "run_other" },
    { ...base, metrics: { private_metric: 1 } },
  ]) {
    const page = browser();
    try {
      page.send("snapshot", { events: [event], cursor: 1, reset: false });
      assert.equal(page.rows().length, 0);
      assert.equal(page.source.closed, true);
    } finally { page.dom.window.close(); }
  }
  const page = browser();
  try {
    page.send("timeline", { event: { ...base, summary: "<img src=x onerror=alert(1)>" } });
    assert.equal(page.rows().length, 1);
    assert.equal(page.window.document.querySelector("img"), null);
  } finally { page.dom.window.close(); }
});
