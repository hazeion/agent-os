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

function browser(fullRuns = false) {
  const dom = new JSDOM(fullRuns ? '<!doctype html><html><body><section data-runs-root><p data-runs-summary></p><button data-runs-refresh>Refresh</button><div data-runs-list></div></section></body></html>' : '<!doctype html><html><body><article id="card"><button id="open">Open timeline</button></article></body></html>', {
    url: "http://127.0.0.1:8888/runs", runScripts: "outside-only", pretendToBeVisual: true,
  });
  const { window } = dom;
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;
  window.requestAnimationFrame = () => 0;
  Object.assign(window, { TextDecoder });
  class TimelineSource extends window.EventTarget {
    static CONNECTING = 0;
    closed = false;
    readyState = 1;
    close() { this.closed = true; }
  }
  const sources: TimelineSource[] = [];
  Object.assign(window, { EventSource: class extends TimelineSource { constructor() { super(); sources.push(this); } } });
  window.eval(runtime);
  if (fullRuns) {
    window.eval(`renderRuns([${JSON.stringify(runFixture())}], [{ id: "agent_test", name: "Test Agent", runtime_type: "codex", capabilities: ["run.events", "run.stop", "run.message"] }]); openRunTimeline(${JSON.stringify(runFixture())}, document.querySelector(".run-card"), document.querySelector("[data-run-timeline-open]"));`);
  } else window.eval('openRunTimeline({ id: "run_timeline_contract" }, document.getElementById("card"), document.getElementById("open"))');
  return {
    dom, window,
    get source() { return sources.at(-1)!; },
    send(type: string, value: unknown) { sources.at(-1)!.dispatchEvent(new window.MessageEvent(type, { data: JSON.stringify(value) })); },
    rows: () => window.document.querySelectorAll("[data-run-event-sequence]"),
    notice: () => window.document.querySelector("[data-run-timeline-notice]")?.textContent,
  };
}

function runFixture() {
  return { id: "run_timeline_contract", agent_id: "agent_test", task_id: "task_test", source: "task", runtime_type: "codex", status: "running", dispatch_state: "accepted", partial: false, timeline_truncated: false, created_at: "2026-09-21T12:00:00Z", updated_at: "2026-09-21T12:00:01Z", started_at: "2026-09-21T12:00:01Z", completed_at: null as string | null };
}

function runsPayload(run = runFixture()) { return { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", count: 1, runs: [run] }; }

test("terminal timeline hints reconcile the canonical card, retain its timeline and close stale controls", { timeout: 5000 }, async () => {
  const page = browser(true);
  try {
    let finish!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finish = resolve; });
    let started!: () => void;
    const readStarted = new Promise<void>((resolve) => { started = resolve; });
    let calls = 0;
    page.window.fetch = async (input) => { assert.equal(input, "/api/runs"); calls += 1; started(); return calls === 1 ? pending : Response.json(runsPayload({ ...runFixture(), status: "completed", completed_at: "2026-09-21T12:01:00Z" })); };
    const completed = { ...fixtures[0].events[0], type: "run.completed", presentation: null, summary: "Run completed" };
    page.send("timeline", { event: completed });
    assert.equal(page.window.document.querySelector(".run-status")?.textContent, "Checking");
    assert.equal((page.window.document.querySelector("[data-run-stop-open]") as HTMLButtonElement).disabled, true);
    await readStarted;
    page.send("timeline", { event: { ...completed, sequence: completed.sequence + 1 } });
    assert.equal(calls, 1, "event burst must not overlap readback requests");
    const panel = page.window.document.querySelector("[data-run-timeline]");
    finish(Response.json(runsPayload({ ...runFixture(), status: "completed", completed_at: "2026-09-21T12:01:00Z" })));
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(page.window.document.querySelector(".run-status")?.textContent, "Checking", "one trailing read remains pending");
    await new Promise((resolve) => setTimeout(resolve, 300));
    assert.equal(calls, 2);
    assert.equal(page.window.document.querySelector(".run-status")?.textContent, "Completed");
    assert.equal(page.window.document.querySelector("[data-run-stop-open]"), null);
    assert.equal(page.window.document.querySelector("[data-run-message-open]"), null);
    assert.equal(page.window.document.querySelector("[data-run-timeline]"), panel);
    assert.equal(page.rows().length, 2);
    assert.equal(page.source.closed, false);
    assert.equal(page.window.document.querySelector('a[href="/tasks?task=task_test"]')?.textContent, "Open Task and result");
  } finally { page.dom.window.close(); }
});

test("failed canonical readback keeps controls closed and late results cannot resurrect a closed timeline", { timeout: 5000 }, async () => {
  const page = browser(true);
  try {
    let finish!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finish = resolve; });
    let started!: () => void;
    const readStarted = new Promise<void>((resolve) => { started = resolve; });
    page.window.fetch = async () => { started(); return pending; };
    const event = { ...fixtures[0].events[0], type: "run.completed", presentation: null, summary: "Run completed" };
    page.send("timeline", { event }); await readStarted;
    finish(Response.json({ ...runsPayload(), private_reference: "untrusted" }));
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(page.window.document.querySelector(".run-status")?.textContent, "Checking");
    assert.equal((page.window.document.querySelector("[data-run-stop-open]") as HTMLButtonElement).disabled, true);
    page.window.eval("closeActiveRunTimeline()");
    assert.equal(page.source.closed, true);
    assert.equal(page.window.document.querySelector("[data-run-timeline]"), null);
    assert.equal(page.window.document.querySelector(".run-status")?.textContent, "Status unavailable");
    const retry = page.window.document.querySelector("[data-run-status-retry]") as HTMLButtonElement;
    assert.equal(retry.textContent, "Refresh status");
    page.window.fetch = async () => Response.json(runsPayload({ ...runFixture(), status: "completed", completed_at: "2026-09-21T12:01:00Z" }));
    retry.click();
    await new Promise((resolve) => setTimeout(resolve, 50));
    assert.equal(page.window.document.querySelector(".run-status")?.textContent, "Completed");
  } finally { page.dom.window.close(); }
});

test("canonical timeline refresh preserves same-Run and unrelated message drafts", { timeout: 5000 }, async () => {
  for (const messageRunId of ["run_timeline_contract", "run_other"]) {
    const page = browser(true);
    try {
      const messageRun = { ...runFixture(), id: messageRunId };
      if (messageRunId === "run_other") page.window.eval(`document.querySelector("[data-runs-list]").append(createRunCard(${JSON.stringify(messageRun)}, [{ id: "agent_test", name: "Test Agent", runtime_type: "codex", capabilities: ["run.events", "run.message"] }], 1));`);
      page.window.eval(`openRunMessage(${JSON.stringify(messageRun)}, document.querySelector('[data-run-id="${messageRunId}"].run-card'), document.querySelector('[data-run-id="${messageRunId}"][data-run-message-open]'));`);
      const draft = page.window.document.querySelector(".run-message textarea") as HTMLTextAreaElement;
      draft.value = "Keep my unsent instructions";
      page.window.eval(`openRunTimeline(${JSON.stringify(runFixture())}, document.querySelector('[data-run-id="run_timeline_contract"].run-card'), document.querySelector('[data-run-id="run_timeline_contract"][data-run-timeline-open]'));`);
      let started!: () => void; const readStarted = new Promise<void>((resolve) => { started = resolve; });
      page.window.fetch = async () => { started(); return Response.json(runsPayload()); };
      page.send("timeline", { event: { ...fixtures[0].events[0], type: "run.started", presentation: null, summary: "Run started" } });
      await readStarted; await new Promise((resolve) => setTimeout(resolve, 30));
      assert.equal(page.window.document.querySelector(".run-message textarea"), draft);
      assert.equal(draft.value, "Keep my unsent instructions");
      assert.equal(draft.disabled, false);
    } finally { page.dom.window.close(); }
  }
});

test("a late Stop preview cannot reopen controls after terminal canonical readback", { timeout: 5000 }, async () => {
  const page = browser(true);
  try {
    let finishPreview!: (response: Response) => void;
    const preview = new Promise<Response>((resolve) => { finishPreview = resolve; });
    let canonicalRead!: () => void;
    const read = new Promise<void>((resolve) => { canonicalRead = resolve; });
    let mutations = 0;
    page.window.fetch = async (input) => {
      if (String(input).endsWith("/stop/preview")) return preview;
      if (input === "/api/runs") { canonicalRead(); return Response.json(runsPayload({ ...runFixture(), status: "completed", completed_at: "2026-09-21T12:01:00Z" })); }
      mutations += 1; throw new Error("unexpected mutation");
    };
    page.window.eval(`void openRunStop(${JSON.stringify(runFixture())}, document.querySelector(".run-card"), document.querySelector("[data-run-stop-open]")); openRunTimeline(${JSON.stringify(runFixture())}, document.querySelector(".run-card"), document.querySelector("[data-run-timeline-open]"));`);
    page.send("timeline", { event: { ...fixtures[0].events[0], type: "run.completed", presentation: null, summary: "Run completed" } });
    await read; await new Promise((resolve) => setTimeout(resolve, 30));
    finishPreview(Response.json({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", action: "stop", run_id: "run_timeline_contract", requires_confirmation: true, confirmation_id: "a".repeat(64) }));
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal((page.window.document.querySelector("[data-run-stop-confirm]") as HTMLButtonElement).disabled, true);
    await page.window.eval("confirmRunStop()");
    assert.equal(mutations, 0);
    assert.equal(page.window.document.querySelector(".run-status")?.textContent, "Completed");
  } finally { page.dom.window.close(); }
});

test("an already reviewed message cannot be sent during uncertain timeline readback", { timeout: 5000 }, async () => {
  const page = browser(true);
  try {
    let mutations = 0;
    page.window.fetch = async (input) => {
      if (String(input).endsWith("/message/preview")) return Response.json({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", action: "message", run_id: "run_timeline_contract", requires_confirmation: true, confirmation_id: "a".repeat(64) });
      if (input === "/api/runs") return Response.json({}, { status: 503 });
      mutations += 1; throw new Error("unexpected mutation");
    };
    page.window.eval(`openRunMessage(${JSON.stringify(runFixture())}, document.querySelector(".run-card"), document.querySelector("[data-run-message-open]"));`);
    (page.window.document.querySelector(".run-message textarea") as HTMLTextAreaElement).value = "Keep this draft";
    await page.window.eval("reviewRunMessage()");
    const confirm = page.window.document.querySelector("[data-run-message-confirm]") as HTMLButtonElement;
    assert.equal(confirm.hidden, false);
    page.window.eval(`openRunTimeline(${JSON.stringify(runFixture())}, document.querySelector(".run-card"), document.querySelector("[data-run-timeline-open]"));`);
    page.send("timeline", { event: { ...fixtures[0].events[0], type: "run.completed", presentation: null, summary: "Run completed" } });
    assert.equal(confirm.disabled, true);
    await page.window.eval("confirmRunMessage()");
    assert.equal(mutations, 0);
    assert.equal((page.window.document.querySelector(".run-message textarea") as HTMLTextAreaElement).value, "Keep this draft");
  } finally { page.dom.window.close(); }
});
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
