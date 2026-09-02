import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { JSDOM } from "jsdom";
import { useState } from "react";
import type { PublicConversationPlanningContext } from "../src/lib/public-planning.ts";
import { nextBrowserTaskReminderDelay } from "../src/lib/browser-task-reminders.ts";

const origin = "http://127.0.0.1:8890";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { pretendToBeVisual: true, url: `${origin}/tasks` });
for (const name of ["CSS", "document", "HTMLElement", "KeyboardEvent", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) {
  Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
}
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
if (!globalThis.CSS) Object.defineProperty(globalThis, "CSS", { configurable: true, value: { escape: (value: string) => value.replace(/[^A-Za-z0-9_-]/gu, "_") } });
else if (!globalThis.CSS.escape) globalThis.CSS.escape = (value) => value.replace(/[^A-Za-z0-9_-]/gu, "_");
HTMLElement.prototype.scrollIntoView = () => undefined;
Object.defineProperty(globalThis, "ResizeObserver", { configurable: true, value: class { disconnect() {} observe() {} unobserve() {} } });
Object.defineProperty(globalThis, "cancelAnimationFrame", { configurable: true, value: (handle: number) => dom.window.clearTimeout(handle) });
Object.defineProperty(globalThis, "requestAnimationFrame", { configurable: true, value: (callback: FrameRequestCallback) => dom.window.setTimeout(() => callback(Date.now()), 0) });

const { cleanup, fireEvent, render, screen, waitFor, within } = await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { ConversationPlanningControls, PlanningAttention, PlanningSuggestions } = await import("../src/app/conversation-planning.tsx");
const { ProjectsTasksWorkspace } = await import("../src/app/tasks/projects-tasks-workspace.tsx");
const { default: TaskDependencyMap, TaskDependencyMapFallback, layoutTaskDependencyMap } = await import("../src/app/tasks/task-dependency-map.tsx");

const envelope = { runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" } as const;
const project = { id: "project_alpha", name: "Alpha", revision: 1, status: "active" as const };
const task = { attention_reasons: ["overdue" as const], blocked: false, deferred: false, due_date: "2026-08-29", id: "task_alpha", needs_attention: true, planned_for_today: false, planning_state: "planned" as const, priority: "high" as const, project_id: project.id, project_name: project.name, review_required: false, revision: 1, status: "todo" as const, title: "Ship Alpha", updated_at: "2026-08-29T12:00:00Z", workflow_stage: "planned" as const };
const listTask = { ...task, description_preview: "Ship the reviewed Alpha changes." };
const taskDetail = { ...task, assigned_agent_id: null, calendar_links: [], description: "Ship the reviewed Alpha changes.", estimated_minutes: null, note_links: [], recurrence: null, reminders: [], scheduled_block: null, subtasks: [], tags: [] };
const dependency = { blocked: false, id: "task_beta", project_id: "project_beta", project_name: "Beta", title: "Prepare Beta", workflow_stage: "planned" as const };
const dependencies = { ...envelope, dependent_count: 1, dependents: [dependency], dependents_truncated: false, prerequisite_count: 0, prerequisites: [], prerequisites_truncated: false, task_id: task.id, task_revision: task.revision };
const picker = { ...envelope, candidate_count: 1, candidates: [dependency], match_count: 1, next_cursor: null, query: "", task_id: task.id, truncated: false };
const overview = { ...envelope, attention: [task], attention_count: 1, project_count: 1, projects: [project], today: "2026-08-30", truncated: false };
const emptyContext = { ...envelope, association: null, conversation_id: "conv_plan", conversation_revision: 1, project: null, state: "empty" as const, task: null };
const readyContext = { ...envelope, association: { project_id: project.id, task_id: task.id }, conversation_id: "conv_plan", conversation_revision: 2, project, state: "ready" as const, task };
const conversation = { agent_id: "agent_alpha", archived_at: null, created_at: "2026-08-29T12:00:00Z", id: "conv_plan", revision: 2, state: "active" as const, title: "Plan", title_source: "manual" as const, updated_at: "2026-08-29T12:01:00Z" };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; }); return { promise, resolve, reject }; }

const dependencyMap = {
  edge_count: 1,
  edge_total: 1,
  edges: [{ from_task_id: task.id, to_task_id: dependency.id }],
  edges_truncated: false,
  external_stub_count: 1,
  external_stub_total: 1,
  external_stubs: [dependency],
  external_stubs_truncated: false,
  node_count: 1,
  node_total: 1,
  nodes: [{ ...dependency, id: task.id, project_id: project.id, project_name: project.name, title: task.title }],
  nodes_truncated: false,
  project_id: project.id,
} as const;

afterEach(() => { cleanup(); window.localStorage.clear(); });

test("Task integrations use dedicated exact mutations and request notification permission only after a user action", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const requests: Array<{ body: Record<string, unknown>; path: string }> = [];
  let permissionCalls = 0;
  const delivered: Array<{ body: string; title: string }> = [];
  class BrowserNotification {
    static permission: NotificationPermission = "default";
    static async requestPermission() { permissionCalls += 1; BrowserNotification.permission = "granted"; return BrowserNotification.permission; }
    constructor(title: string, options?: NotificationOptions) { delivered.push({ body: options?.body ?? "", title }); }
  }
  Object.defineProperty(globalThis, "Notification", { configurable: true, value: BrowserNotification });
  Object.defineProperty(window, "Notification", { configurable: true, value: BrowserNotification });
  const detailed = { ...taskDetail, revision: 1 };
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [{ ...listTask, revision: 1 }] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: detailed });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_revision: 1 });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json({ ...envelope, execution: { attempt_count: 0, attempts: [], available: false, reason: "unavailable", review: { available: false, run_id: null } }, task: { ...task, assigned_agent_id: null, revision: 1 } });
    if (url.pathname === "/api/agent-console/planning-task-delegation") return Response.json({ ...envelope, delegation: { available: false, reason: "not_delegated" }, task: { id: task.id, revision: 1 } });
    if (url.pathname === "/api/agent-console/planning-calendar") { const start = url.searchParams.get("week_start")!; const end = new Date(`${start}T00:00:00Z`); end.setUTCDate(end.getUTCDate() + 7); return Response.json({ ...envelope, calendar_id: "primary", event_count: 1, events: [{ all_day: false, end: "2026-09-08T21:00:00Z", id: "event_alpha", start: "2026-09-08T20:00:00Z", title: "Focus" }], label: "This week", read_only: true, timezone: url.searchParams.get("timezone"), week_end: end.toISOString().slice(0, 10), week_start: start }); }
    if (url.pathname === "/api/agent-console/planning-note-picker") return Response.json({ ...envelope, available: true, count: 1, notes: [{ path: "Plans/Alpha.md", title: "Alpha" }], query: url.searchParams.get("q") ?? "", truncated: false });
    if (url.pathname.includes("/integrations/")) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>; requests.push({ body, path: url.pathname });
      const action = url.pathname.endsWith("/reminders") ? "replace_reminders" : url.pathname.endsWith("/notes/attach") ? "attach_note" : "calendar_link";
      const nextRevision = Number(body.expected_revision) + 1;
      const next = { ...detailed, revision: nextRevision, reminders: action === "replace_reminders" ? (body.reminders as Array<{ at: string; enabled: boolean; id: string; timezone?: string }>).map((reminder) => ({ ...reminder, channel: "browser" as const })) : detailed.reminders, note_links: action === "attach_note" ? [{ path: "Plans/Alpha.md", title: "Alpha" }] : detailed.note_links, calendar_links: action === "calendar_link" ? [{ calendar_id: "primary", event_id: "event_alpha", label: "Focus" }] : detailed.calendar_links };
      return Response.json({ ...envelope, action, project, task: next });
    }
    throw new Error(`unexpected ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await screen.findByRole("button", { name: "Manage reminders" });
  assert.equal(permissionCalls, 0);
  await user.click(screen.getByRole("button", { name: "Enable browser notifications" }));
  await waitFor(() => assert.equal(permissionCalls, 1));
  await user.click(screen.getByRole("button", { name: "Manage reminders" }));
  await user.click(screen.getByRole("button", { name: "Add reminder" }));
  fireEvent.change(screen.getByLabelText("Reminder 1 time"), { target: { value: "2020-09-03T09:00" } });
  await user.click(screen.getByRole("button", { name: "Save reminders" }));
  await waitFor(() => assert.equal(requests[0]?.path, `/api/planning/tasks/${task.id}/integrations/reminders`));
  assert.deepEqual(Object.keys(requests[0]!.body).sort(), ["expected_revision", "reminders"]);
  await waitFor(() => assert.deepEqual(delivered, [{ body: task.title, title: "Mentat reminder" }]));
  await user.click(screen.getByRole("button", { name: "Link calendar event" }));
  await screen.findByText("Focus");
  await user.click(screen.getByRole("button", { name: "Link" }));
  await waitFor(() => assert.equal(requests[1]?.path, `/api/planning/tasks/${task.id}/integrations/calendar/link`));
  await waitFor(() => assert.equal((screen.getByRole("button", { name: "Attach note" }) as HTMLButtonElement).disabled, false));
  await user.click(screen.getByRole("button", { name: "Attach note" }));
  await user.type(screen.getByRole("searchbox", { name: "Find a note" }), "Alpha");
  await screen.findByRole("button", { name: "Attach" });
  await user.click(screen.getByRole("button", { name: "Attach" }));
  await waitFor(() => assert.equal(requests[2]?.path, `/api/planning/tasks/${task.id}/integrations/notes/attach`));
  assert.equal(permissionCalls, 1);
});

test("the read-only dependency-map fallback is deterministic, keyboard-selectable, and keeps external stubs noninteractive", () => {
  const first = layoutTaskDependencyMap(dependencyMap);
  const second = layoutTaskDependencyMap(dependencyMap);
  assert.deepEqual(first, second);
  assert.equal(first.nodes.find((node) => node.id === task.id)?.layer, 0);
  assert.equal(first.nodes.find((node) => node.id === dependency.id)?.layer, 1);
  const selected: string[] = [];
  render(<TaskDependencyMapFallback graph={dependencyMap} onSelectedTaskIdChange={(taskId) => selected.push(taskId)} selectedTaskId={null} />);
  const source = screen.getByRole("button", { name: /Ship Alpha, Task, planned/u });
  fireEvent.keyDown(source, { key: "Enter" });
  assert.deepEqual(selected, [task.id]);
  const external = screen.getByRole("img", { name: /Prepare Beta, cross-project reference/u });
  fireEvent.click(external);
  fireEvent.keyDown(external, { key: "Enter" });
  assert.deepEqual(selected, [task.id]);
});

test("client dependency-map layout remains deterministic and hard-capped when a hostile caller bypasses the route projection", () => {
  // The server contract permits at most 100 visible references and 250 edges.
  // Exercise the source-owned renderer's independent ceiling as a second line
  // of defense: callers of the pure layout cannot accidentally turn a stale or
  // future projection into an unbounded DOM/canvas workload.
  const nodes = Array.from({ length: 150 }, (_, index) => ({
    blocked: false,
    id: `task_render_${index.toString().padStart(3, "0")}`,
    project_id: project.id,
    project_name: project.name,
    title: `Render Task ${index.toString().padStart(3, "0")}`,
    workflow_stage: "planned" as const,
  }));
  const edges: Array<{ from_task_id: string; to_task_id: string }> = [];
  for (let source = 0; source < 128 && edges.length < 300; source += 1) {
    for (let target = source + 1; target < 128 && edges.length < 300; target += 1) {
      edges.push({
        from_task_id: `task_render_${source.toString().padStart(3, "0")}`,
        to_task_id: `task_render_${target.toString().padStart(3, "0")}`,
      });
    }
  }
  const graph = {
    edge_count: edges.length,
    edge_total: edges.length,
    edges,
    edges_truncated: true,
    external_stub_count: 0,
    external_stub_total: 0,
    external_stubs: [],
    external_stubs_truncated: false,
    node_count: nodes.length,
    node_total: nodes.length,
    nodes,
    nodes_truncated: true,
    project_id: project.id,
  };
  const first = layoutTaskDependencyMap(graph);
  const second = layoutTaskDependencyMap(graph);
  assert.deepEqual(first, second);
  assert.equal(first.nodes.length, 128);
  assert.equal(first.edges.length, 256);
  assert.deepEqual(
    [...first.nodes.map((node) => node.id)].sort(),
    Array.from({ length: 128 }, (_, index) => `task_render_${index.toString().padStart(3, "0")}`),
  );
  assert.deepEqual({ nodes: first.omitted_nodes, edges: first.omitted_edges }, { nodes: 22, edges: 44 });
});

test("the desktop dependency map includes edge endpoints and activates each Task once", async () => {
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ addEventListener: () => undefined, matches: false, removeEventListener: () => undefined }) });
  const selected: string[] = [];
  render(<TaskDependencyMap graph={dependencyMap} onSelectedTaskIdChange={(taskId) => selected.push(taskId)} selectedTaskId={null} />);
  await screen.findByRole("application", { name: "Interactive task dependency map" });
  await waitFor(() => assert.equal(document.querySelectorAll(".react-flow__handle").length, 4));
  const source = document.querySelector<HTMLButtonElement>('button[aria-label="Ship Alpha, Task, planned"]');
  assert.ok(source);
  fireEvent.click(source);
  assert.deepEqual(selected, [task.id]);
});

test("Map is opt-in, follows the shared filter, and selects through the existing Task inspector", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ addEventListener: () => undefined, matches: true, removeEventListener: () => undefined }) });
  let mapReads = 0;
  let failDetailAfterUpdate = false;
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-dependency-map") {
      const { project_id, ...mapPayload } = dependencyMap; void project_id; mapReads += 1;
      if (url.searchParams.has("q")) return Response.json({ ...envelope, ...mapPayload, edge_count: 0, edge_total: 0, edges: [], external_stub_count: 0, external_stub_total: 0, external_stubs: [], node_count: 0, node_total: 0, nodes: [], project });
      return Response.json({ ...envelope, ...mapPayload, project });
    }
    if (url.pathname === "/api/agent-console/planning-task-detail") return failDetailAfterUpdate ? Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 }) : Response.json({ ...envelope, project, task: taskDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === `/api/planning/tasks/${task.id}/edit`) { failDetailAfterUpdate = true; return Response.json({ ...envelope, action: "edit", project, task: { ...task, revision: 2, workflow_stage: "waiting" } }); }
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await screen.findByText("Ship Alpha");
  assert.equal(mapReads, 0);
  await user.click(screen.getByRole("button", { name: "Map" }));
  const source = await screen.findByRole("button", { name: /Ship Alpha, Task, planned/u });
  assert.equal(mapReads, 1);
  await user.click(source);
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /Selected Task Ship Alpha/u));
  const moveToWaiting = screen.getAllByRole("button", { name: "waiting" }).find((button) => button.closest('[aria-label="Task inspector"]'));
  assert.ok(moveToWaiting);
  await user.click(moveToWaiting);
  await waitFor(() => assert.equal(mapReads, 2));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /refreshed details are temporarily unavailable/u));
  await user.type(screen.getByLabelText("Filter"), "no matching task");
  await screen.findByText("No dependency map is available for this Project.");
});

test("Task execution stays unavailable until its safe projection arrives, then previews and starts one exact Run", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const executionTask = { ...task, assigned_agent_id: "agent_alpha", workflow_stage: "planned" as const };
  const execution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: executionTask };
  const preview = { ...envelope, action: "run_once" as const, confirmation_id: "a".repeat(64), requires_confirmation: true as const, task: executionTask };
  const started = { ...envelope, action: "run_once" as const, duplicate: false, execution: { attempt_count: 1, attempts: [{ agent_id: "agent_alpha", completed_at: null, completion_reason: null, created_at: "2026-08-30T12:00:00Z", dispatch_state: "accepted", partial: false, review_action: null, review_note: null, review_task_revision: null, run_id: "run_alpha", runtime_type: "codex", state: "dispatched" as const, status: "running", task_revision: 1, terminal_finalized: false, updated_at: "2026-08-30T12:00:00Z" }], available: false, reason: "unavailable" as const, review: { available: false, run_id: null } }, task: { ...executionTask, revision: 2, workflow_stage: "in_progress" as const, planning_state: "in_progress" as const, status: "in progress" as const } };
  const calls: Array<{ body: unknown; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); calls.push({ body: init?.body ? JSON.parse(String(init.body)) : null, path: `${url.pathname}${url.search}` });
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(calls.some((call) => call.path.endsWith("/execution/run-once")) ? { ...envelope, execution: started.execution, task: started.task } : execution);
    if (url.pathname.endsWith("/execution/run-once/preview")) return Response.json(preview);
    if (url.pathname.endsWith("/execution/run-once")) return Response.json(started, { status: 202 });
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: { ...task, revision: 2, workflow_stage: "in_progress", status: "in progress", planning_state: "in_progress" } });
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await screen.findByRole("button", { name: "Run once" });
  await user.click(screen.getByRole("button", { name: "Run once" }));
  await screen.findByRole("button", { name: "Start Run once" });
  await user.click(screen.getByRole("button", { name: "Start Run once" }));
  await screen.findByText("Run once started.");
  const inspector = screen.getByLabelText("Task inspector");
  assert.equal((within(inspector).getByRole("button", { name: "review" }) as HTMLButtonElement).disabled, true);
  assert.equal((within(inspector).getByRole("button", { name: "done" }) as HTMLButtonElement).disabled, true);
  assert.match(within(inspector).getByText(/Run and review controls own/u).textContent ?? "", /Review and Done/u);
  const previewCall = calls.find((call) => call.path.endsWith("/execution/run-once/preview"));
  const confirmCall = calls.find((call) => call.path.endsWith("/execution/run-once"));
  assert.deepEqual(previewCall?.body, { expected_revision: 1 });
  assert.equal(typeof (confirmCall?.body as { idempotency_key?: unknown } | undefined)?.idempotency_key, "string");
  assert.deepEqual({ ...(confirmCall?.body as Record<string, unknown>), idempotency_key: "opaque" }, { confirmation_id: preview.confirmation_id, expected_revision: 1, idempotency_key: "opaque" });
});

test("Task inspector presents the bounded delegation summary and an honest not-delegated state", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const beta = { ...task, id: "task_beta", title: "Prepare Beta" };
  const betaList = { ...listTask, id: beta.id, title: beta.title, description_preview: "Prepare the Beta changes." };
  const execution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: { ...task, assigned_agent_id: "agent_alpha" } };
  const delegation = { ...envelope, delegation: { artifact_count: 0, attempts: 2, available: true as const, last_outcome: "completed" as const, last_synced_at: "2026-08-30T11:59:00Z", latest_question: "Confirm the deployment window.", review_state: "pending" as const, state: "ready_for_review" as const, summary: "The delegated implementation is ready for review.", sync_state: "synced" as const, updated_at: "2026-08-30T12:00:00Z" }, task: { id: task.id, revision: task.revision } };
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin); const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, betaList] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, description: "Prepare the Beta changes." } : taskDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? task.id });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json({ ...execution, task: taskId === beta.id ? { ...execution.task, ...beta } : execution.task });
    if (url.pathname === "/api/agent-console/planning-task-delegation") return Response.json(taskId === beta.id ? { ...envelope, delegation: { available: false, reason: "not_delegated" }, task: { id: beta.id, revision: beta.revision } } : delegation);
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  const inspector = screen.getByLabelText("Task inspector");
  const delegationPanel = await within(inspector).findByLabelText("Task delegation");
  assert.match(within(delegationPanel).getByText("ready for review").textContent ?? "", /ready for review/u);
  assert.match(within(delegationPanel).getByText(/The delegated implementation/u).textContent ?? "", /Summary/u);
  assert.match(within(delegationPanel).getByText(/Confirm the deployment window/u).textContent ?? "", /Needs input/u);
  await user.click(screen.getByRole("button", { name: /Prepare Beta/u }));
  await within(inspector).findByText("Prepare the Beta changes.");
  await within(inspector).findByText("This Task has not been delegated.");
  assert.equal(within(inspector).queryByText(/The delegated implementation is ready/u), null);
});

test("Task inspector presents selected Task planning details as bounded, read-only labels", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const detail = {
    ...taskDetail,
    calendar_links: [
      { calendar_id: "calendar_alpha", event_id: "event_alpha", label: "Alpha review" },
      { calendar_id: "calendar_beta", event_id: "event_beta" },
    ],
    note_links: [
      { path: "planning/alpha-brief.md", title: "Alpha brief" },
      { path: "planning/release-checklist.md" },
    ],
    reminders: [
      { at: "2026-09-02T09:00:00Z", channel: "browser" as const, enabled: true, id: "reminder_alpha", timezone: "UTC" },
      { at: "2026-09-02T10:00:00Z", channel: "browser" as const, enabled: false, id: "reminder_beta", notified_at: "2026-09-02T09:55:00Z", timezone: "UTC" },
    ],
    scheduled_block: { end: "2026-09-02T10:30:00Z", label: "Focus block", start: "2026-09-02T09:30:00Z", timezone: "UTC" },
  };
  const calls: Array<{ method: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); calls.push({ method: init?.method ?? "GET", path: url.pathname });
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: detail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json({ ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task });
    if (url.pathname === "/api/agent-console/planning-task-delegation") return Response.json({ ...envelope, delegation: { available: false, reason: "not_delegated" }, task: { id: task.id, revision: task.revision } });
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  const inspector = screen.getByLabelText("Task inspector");
  const planning = await within(inspector).findByLabelText("Planning details");
  assert.match(within(planning).getByText("Focus block").textContent ?? "", /Focus block/u);
  assert.equal(planning.querySelectorAll("time").length, 4);
  assert.match(within(planning).getByLabelText("Browser reminders").textContent ?? "", /On.*Off.*Sent/us);
  assert.match(within(planning).getByLabelText("Calendar links").textContent ?? "", /Alpha review.*Linked calendar event 2/us);
  assert.match(within(planning).getByLabelText("Notes").textContent ?? "", /Alpha brief.*release-checklist/us);
  assert.equal(within(planning).queryAllByRole("button").length, 0);
  assert.equal(within(planning).queryAllByRole("link").length, 0);
  assert.ok(calls.every((call) => call.method === "GET"));
});

test("an indeterminate delegation delivery can only be reconciled, never confirmed again", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const execution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task };
  const current = { ...envelope, delegation: { available: false as const, reason: "not_delegated" as const }, task: { id: task.id, revision: task.revision } };
  const options = { ...current, options: { available: true as const, boards: [{ id: "default", name: "Default" }], profiles: [{ id: "researcher", name: "Researcher" }], workspaces: ["scratch", "worktree"] as ["scratch", "worktree"] } };
  const preview = { ...current, action: "delegate" as const, confirmation_id: `task_delegate_${"a".repeat(24)}`, effects: ["Create one Hermes Task."], requires_confirmation: true as const, target: { board_id: "default", profile_id: "researcher", workspace: "scratch" as const } };
  const calls: Array<{ body: unknown; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); calls.push({ body: init?.body ? JSON.parse(String(init.body)) : null, path: url.pathname });
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(execution);
    if (url.pathname === "/api/agent-console/planning-task-delegation") return Response.json(current);
    if (url.pathname.endsWith("/planning-task-delegation/options")) return Response.json(options);
    if (url.pathname.endsWith("/delegation/preview")) return Response.json(preview);
    if (url.pathname.endsWith("/delegation/delegate")) return Response.json({ error: "unavailable" }, { status: 503 });
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await user.click(await screen.findByRole("button", { name: "Delegate" }));
  await user.click(await screen.findByRole("button", { name: "Preview delegation" }));
  const confirm = await screen.findByRole("button", { name: "Confirm delegation" });
  await user.dblClick(confirm);
  await screen.findByRole("button", { name: "Reconcile prior delivery" });
  assert.equal(calls.filter((call) => call.path.endsWith("/delegation/delegate")).length, 1);
  assert.equal(screen.queryByRole("button", { name: "Confirm delegation" }), null);
  assert.equal(screen.queryByRole("button", { name: "Delegate" }), null);
});

test("an indeterminate delegation action can only be reconciled, never confirmed again", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const execution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task };
  const current = { ...envelope, delegation: { artifact_count: 0, attempts: 1, available: true as const, last_outcome: null, last_synced_at: null, latest_question: null, review_state: "pending" as const, state: "ready_for_review" as const, summary: null, sync_state: "synced" as const, updated_at: "2026-09-02T12:00:00Z" }, task: { id: task.id, revision: task.revision } };
  const preview = { ...current, action: "accept" as const, confirmation_id: `delegation_action_${"b".repeat(24)}`, effects: ["Accept the delegated result."], requires_confirmation: true as const };
  const calls: Array<{ body: unknown; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); calls.push({ body: init?.body ? JSON.parse(String(init.body)) : null, path: url.pathname });
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(execution);
    if (url.pathname === "/api/agent-console/planning-task-delegation") return Response.json(current);
    if (url.pathname.endsWith("/delegation/action/preview")) return Response.json(preview);
    if (url.pathname.endsWith("/delegation/action")) return Response.json({ error: "unavailable" }, { status: 503 });
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await user.click(await screen.findByRole("button", { name: "Accept" }));
  const confirm = await screen.findByRole("button", { name: "Confirm action" });
  await user.dblClick(confirm);
  await screen.findByRole("button", { name: "Reconcile prior delivery" });
  assert.equal(calls.filter((call) => call.path.endsWith("/delegation/action")).length, 1);
  assert.equal(screen.queryByRole("button", { name: "Confirm action" }), null);
  assert.equal(screen.queryByRole("button", { name: "Accept" }), null);
});

test("List selection clears a same-revision Task's pending Run-once confirmation", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const alpha = { ...task, assigned_agent_id: "agent_alpha" };
  const beta = { ...task, assigned_agent_id: "agent_alpha", id: "task_beta", title: "Prepare Beta" };
  const betaList = { ...listTask, id: beta.id, title: beta.title, description_preview: "Prepare the Beta changes." };
  const alphaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: alpha };
  const betaExecution = deferred<Response>();
  const preview = { ...envelope, action: "run_once" as const, confirmation_id: "a".repeat(64), requires_confirmation: true as const, task: alpha };
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, betaList] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, description: "Prepare the Beta changes." } : { ...taskDetail, ...alpha } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? alpha.id });
    if (url.pathname === "/api/agent-console/planning-task-execution") return taskId === beta.id ? betaExecution.promise : Response.json(alphaExecution);
    if (url.pathname.endsWith("/execution/run-once/preview")) return Response.json(preview);
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await user.click(await screen.findByRole("button", { name: "Run once" }));
  await screen.findByRole("button", { name: "Start Run once" });
  await user.click(screen.getByRole("button", { name: /Prepare Beta/u }));
  const inspector = screen.getByLabelText("Task inspector");
  await within(inspector).findByText("Prepare the Beta changes.");
  assert.equal(within(inspector).queryByRole("button", { name: "Start Run once" }), null);
  assert.equal(within(inspector).queryByRole("button", { name: "Accept" }), null);
  betaExecution.resolve(Response.json({ ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: beta }));
  await within(inspector).findByRole("button", { name: "Run once" });
});

test("Map selection clears a same-revision Task's review controls before its execution projection arrives", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ addEventListener: () => undefined, matches: true, removeEventListener: () => undefined }) });
  const alpha = { ...task, assigned_agent_id: "agent_alpha", workflow_stage: "review" as const };
  const beta = { ...task, assigned_agent_id: "agent_alpha", id: "task_beta", title: "Prepare Beta" };
  const betaList = { ...listTask, id: beta.id, title: beta.title, description_preview: "Prepare the Beta changes." };
  const reviewAttempt = { agent_id: "agent_alpha", completed_at: "2026-08-30T12:00:00Z", completion_reason: null, created_at: "2026-08-30T12:00:00Z", dispatch_state: "accepted", partial: false, review_action: null, review_note: null, review_task_revision: null, run_id: "run_alpha", runtime_type: "codex", state: "review_ready" as const, status: "completed", task_revision: 1, terminal_finalized: true, updated_at: "2026-08-30T12:00:00Z" };
  const alphaExecution = { ...envelope, execution: { attempt_count: 1, attempts: [reviewAttempt], available: false, reason: "unavailable" as const, review: { available: true, run_id: "run_alpha" } }, task: alpha };
  const betaExecution = deferred<Response>();
  const map = { ...dependencyMap, edge_count: 1, edge_total: 1, edges: [{ from_task_id: alpha.id, to_task_id: beta.id }], external_stub_count: 0, external_stub_total: 0, external_stubs: [], node_count: 2, node_total: 2, nodes: [{ ...dependencyMap.nodes[0], workflow_stage: "review" as const }, { blocked: false, id: beta.id, project_id: project.id, project_name: project.name, title: beta.title, workflow_stage: "planned" as const }] };
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, betaList] });
    if (url.pathname === "/api/agent-console/planning-dependency-map") { const { project_id, ...payload } = map; void project_id; return Response.json({ ...envelope, ...payload, project }); }
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, description: "Prepare the Beta changes." } : { ...taskDetail, ...alpha } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? alpha.id });
    if (url.pathname === "/api/agent-console/planning-task-execution") return taskId === beta.id ? betaExecution.promise : Response.json(alphaExecution);
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await screen.findByRole("button", { name: "Accept" });
  await user.click(screen.getByRole("button", { name: "Map" }));
  await user.click(await screen.findByRole("button", { name: /Prepare Beta, Task, planned/u }));
  const inspector = screen.getByLabelText("Task inspector");
  await within(inspector).findByText("Prepare the Beta changes.");
  assert.equal(within(inspector).queryByRole("button", { name: "Accept" }), null);
  assert.equal(within(inspector).queryByRole("button", { name: "Start Run once" }), null);
  betaExecution.resolve(Response.json({ ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: beta }));
  await within(inspector).findByRole("button", { name: "Run once" });
});

test("a delayed off-page Map lookup cannot replace a newer List selection", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ addEventListener: () => undefined, matches: true, removeEventListener: () => undefined }) });
  const beta = { ...task, assigned_agent_id: "agent_alpha", id: "task_beta", title: "Prepare Beta" };
  const gamma = { ...task, assigned_agent_id: "agent_alpha", id: "task_gamma", title: "Investigate Gamma" };
  const betaList = { ...listTask, id: beta.id, title: beta.title, description_preview: "Prepare the Beta changes." };
  const gammaLookup = deferred<Response>();
  const alphaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: { ...task, assigned_agent_id: "agent_alpha" } };
  const betaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: beta };
  const map = { ...dependencyMap, edge_count: 1, edge_total: 1, edges: [{ from_task_id: task.id, to_task_id: gamma.id }], external_stub_count: 0, external_stub_total: 0, external_stubs: [], node_count: 3, node_total: 3, nodes: [dependencyMap.nodes[0], { blocked: false, id: beta.id, project_id: project.id, project_name: project.name, title: beta.title, workflow_stage: "planned" as const }, { blocked: false, id: gamma.id, project_id: project.id, project_name: project.name, title: gamma.title, workflow_stage: "planned" as const }] };
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, betaList] });
    if (url.pathname === "/api/agent-console/planning-dependency-map") { const { project_id, ...payload } = map; void project_id; return Response.json({ ...envelope, ...payload, project }); }
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, description: "Prepare the Beta changes." } : { ...taskDetail, ...task } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? task.id });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(taskId === beta.id ? betaExecution : alphaExecution);
    if (url.pathname === "/api/agent-console/planning-task") return taskId === gamma.id ? gammaLookup.promise : Response.json({ ...envelope, project, task: task });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(screen.getByRole("button", { name: "Map" }));
  await user.click(await screen.findByRole("button", { name: /Investigate Gamma, Task, planned/u }));
  await user.click(screen.getByRole("button", { name: "List" }));
  await user.click(screen.getByRole("button", { name: /Prepare Beta/u }));
  const inspector = screen.getByLabelText("Task inspector");
  await within(inspector).findByText("Prepare the Beta changes.");
  gammaLookup.resolve(Response.json({ ...envelope, project, task: gamma }));
  await waitFor(() => {
    assert.match(within(inspector).getByText("Prepare the Beta changes.").textContent ?? "", /Beta changes/u);
    assert.doesNotMatch(screen.getByRole("status").textContent ?? "", /Selected Task Investigate Gamma/u);
  });
});

test("a late Run once preview cannot confirm a Task selected from the dependency map", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ addEventListener: () => undefined, matches: true, removeEventListener: () => undefined }) });
  const alpha = { ...task, assigned_agent_id: "agent_alpha" };
  const beta = { ...task, assigned_agent_id: "agent_alpha", id: "task_beta", title: "Prepare Beta" };
  const betaList = { ...listTask, id: beta.id, title: beta.title, description_preview: "Prepare the Beta changes." };
  const alphaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: alpha };
  const betaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: beta };
  const latePreview = deferred<Response>();
  const map = { ...dependencyMap, edge_count: 1, edge_total: 1, edges: [{ from_task_id: alpha.id, to_task_id: beta.id }], external_stub_count: 0, external_stub_total: 0, external_stubs: [], node_count: 2, node_total: 2, nodes: [dependencyMap.nodes[0], { blocked: false, id: beta.id, project_id: project.id, project_name: project.name, title: beta.title, workflow_stage: "planned" as const }] };
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, betaList] });
    if (url.pathname === "/api/agent-console/planning-dependency-map") { const { project_id, ...payload } = map; void project_id; return Response.json({ ...envelope, ...payload, project }); }
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, description: "Prepare the Beta changes." } : { ...taskDetail, ...alpha } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? alpha.id });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(taskId === beta.id ? betaExecution : alphaExecution);
    if (url.pathname.endsWith("/execution/run-once/preview")) return latePreview.promise;
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: alpha });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await user.click(await screen.findByRole("button", { name: "Run once" }));
  await user.click(screen.getByRole("button", { name: "Map" }));
  await user.click(await screen.findByRole("button", { name: /Prepare Beta, Task, planned/u }));
  const inspector = screen.getByLabelText("Task inspector");
  await within(inspector).findByText("Prepare the Beta changes.");
  await within(inspector).findByRole("button", { name: "Run once" });
  latePreview.resolve(Response.json({ ...envelope, action: "run_once" as const, confirmation_id: "a".repeat(64), requires_confirmation: true as const, task: alpha }));
  await waitFor(() => {
    assert.match(within(inspector).getByText("Prepare the Beta changes.").textContent ?? "", /Beta changes/u);
    assert.ok(within(inspector).getByRole("button", { name: "Run once" }));
    assert.equal(within(inspector).queryByRole("button", { name: "Start Run once" }), null);
    assert.doesNotMatch(screen.getByRole("status").textContent ?? "", /Review the exact Task revision/u);
  });
});

test("a late Run once mutation cannot overwrite a Task selected from the dependency map", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ addEventListener: () => undefined, matches: true, removeEventListener: () => undefined }) });
  const alpha = { ...task, assigned_agent_id: "agent_alpha" };
  const beta = { ...task, assigned_agent_id: "agent_alpha", id: "task_beta", title: "Prepare Beta" };
  const betaList = { ...listTask, id: beta.id, title: beta.title, description_preview: "Prepare the Beta changes." };
  const alphaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: alpha };
  const betaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: beta };
  const preview = { ...envelope, action: "run_once" as const, confirmation_id: "a".repeat(64), requires_confirmation: true as const, task: alpha };
  const lateMutation = deferred<Response>();
  const map = { ...dependencyMap, edge_count: 1, edge_total: 1, edges: [{ from_task_id: alpha.id, to_task_id: beta.id }], external_stub_count: 0, external_stub_total: 0, external_stubs: [], node_count: 2, node_total: 2, nodes: [dependencyMap.nodes[0], { blocked: false, id: beta.id, project_id: project.id, project_name: project.name, title: beta.title, workflow_stage: "planned" as const }] };
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, betaList] });
    if (url.pathname === "/api/agent-console/planning-dependency-map") { const { project_id, ...payload } = map; void project_id; return Response.json({ ...envelope, ...payload, project }); }
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, description: "Prepare the Beta changes." } : { ...taskDetail, ...alpha } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? alpha.id });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(taskId === beta.id ? betaExecution : alphaExecution);
    if (url.pathname.endsWith("/execution/run-once/preview")) return Response.json(preview);
    if (url.pathname.endsWith("/execution/run-once")) return lateMutation.promise;
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: alpha });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await user.click(await screen.findByRole("button", { name: "Run once" }));
  await user.click(await screen.findByRole("button", { name: "Start Run once" }));
  await user.click(screen.getByRole("button", { name: "Map" }));
  await user.click(await screen.findByRole("button", { name: /Prepare Beta, Task, planned/u }));
  const inspector = screen.getByLabelText("Task inspector");
  await within(inspector).findByText("Prepare the Beta changes.");
  await within(inspector).findByRole("button", { name: "Run once" });
  lateMutation.resolve(Response.json({ ...envelope, action: "run_once", duplicate: false, execution: { attempt_count: 1, attempts: [], available: false, reason: "unavailable", review: { available: false, run_id: null } }, task: { ...alpha, revision: 2, workflow_stage: "in_progress", planning_state: "in_progress", status: "in progress" } }, { status: 202 }));
  await waitFor(() => {
    assert.match(within(inspector).getByText("Prepare the Beta changes.").textContent ?? "", /Beta changes/u);
    assert.ok(within(inspector).getByRole("button", { name: "Run once" }));
    assert.doesNotMatch(screen.getByRole("status").textContent ?? "", /Run once started/u);
  });
});

test("a delayed stage save cannot overwrite a Task selected from the dependency map", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ addEventListener: () => undefined, matches: true, removeEventListener: () => undefined }) });
  const alpha = { ...task, assigned_agent_id: "agent_alpha" };
  const beta = { ...task, assigned_agent_id: "agent_alpha", id: "task_beta", title: "Prepare Beta" };
  const betaList = { ...listTask, id: beta.id, title: beta.title, description_preview: "Prepare the Beta changes." };
  const alphaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: alpha };
  const betaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: beta };
  const stageSave = deferred<Response>();
  const map = { ...dependencyMap, edge_count: 1, edge_total: 1, edges: [{ from_task_id: alpha.id, to_task_id: beta.id }], external_stub_count: 0, external_stub_total: 0, external_stubs: [], node_count: 2, node_total: 2, nodes: [dependencyMap.nodes[0], { blocked: false, id: beta.id, project_id: project.id, project_name: project.name, title: beta.title, workflow_stage: "planned" as const }] };
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, betaList] });
    if (url.pathname === "/api/agent-console/planning-dependency-map") { const { project_id, ...payload } = map; void project_id; return Response.json({ ...envelope, ...payload, project }); }
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, description: "Prepare the Beta changes." } : { ...taskDetail, ...alpha } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? alpha.id });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(taskId === beta.id ? betaExecution : alphaExecution);
    if (url.pathname === `/api/planning/tasks/${alpha.id}/edit`) { assert.equal(init?.method, "POST"); return stageSave.promise; }
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await screen.findByRole("button", { name: "Run once" });
  await user.click(screen.getByRole("button", { name: "Map" }));
  const inspector = screen.getByLabelText("Task inspector");
  const moveToWaiting = within(inspector).getByRole("button", { name: "waiting" });
  await user.click(moveToWaiting);
  await user.click(await screen.findByRole("button", { name: /Prepare Beta, Task, planned/u }));
  await within(inspector).findByText("Prepare the Beta changes.");
  stageSave.resolve(Response.json({ ...envelope, action: "edit", project, task: { ...alpha, revision: 2, workflow_stage: "waiting" as const } }));
  await waitFor(() => {
    assert.match(within(inspector).getByText("Prepare the Beta changes.").textContent ?? "", /Beta changes/u);
    assert.doesNotMatch(screen.getByRole("status").textContent ?? "", /Task moved to waiting/u);
  });
});

test("a stage revision change hides stale review actions until its execution refresh arrives", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const alpha = { ...task, assigned_agent_id: "agent_alpha", workflow_stage: "review" as const };
  const updatedTask = { ...task, revision: 2, workflow_stage: "waiting" as const };
  const updated = { ...updatedTask, assigned_agent_id: "agent_alpha" };
  const reviewAttempt = { agent_id: "agent_alpha", completed_at: "2026-08-30T12:00:00Z", completion_reason: null, created_at: "2026-08-30T12:00:00Z", dispatch_state: "accepted", partial: false, review_action: null, review_note: null, review_task_revision: null, run_id: "run_alpha", runtime_type: "codex", state: "review_ready" as const, status: "completed", task_revision: 1, terminal_finalized: true, updated_at: "2026-08-30T12:00:00Z" };
  const reviewExecution = { ...envelope, execution: { attempt_count: 1, attempts: [reviewAttempt], available: false, reason: "unavailable" as const, review: { available: true, run_id: "run_alpha" } }, task: alpha };
  const refreshedExecution = { ...envelope, execution: { attempt_count: 1, attempts: [reviewAttempt], available: false, reason: "unavailable" as const, review: { available: false, run_id: null } }, task: updated };
  const staleDetail = deferred<Response>();
  let stageSaved = false;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [{ ...listTask, workflow_stage: "review" }] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return stageSaved ? staleDetail.promise : Response.json({ ...envelope, project, task: { ...taskDetail, ...alpha } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_revision: stageSaved ? updated.revision : alpha.revision });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(stageSaved ? refreshedExecution : reviewExecution);
    if (url.pathname === `/api/planning/tasks/${alpha.id}/edit`) { assert.equal(init?.method, "POST"); stageSaved = true; return Response.json({ ...envelope, action: "edit", project, task: updatedTask }); }
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: stageSaved ? updatedTask : alpha });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await screen.findByRole("button", { name: "Accept" });
  const inspector = screen.getByLabelText("Task inspector");
  await user.click(within(inspector).getByRole("button", { name: "waiting" }));
  await waitFor(() => {
    if (within(inspector).queryByRole("button", { name: "Accept" })) throw new Error(`Accept remains visible: ${screen.getByRole("status").textContent ?? "no status"}`);
  });
  assert.match(within(inspector).getByText("Run once and review controls are temporarily unavailable.").textContent ?? "", /temporarily unavailable/u);
  staleDetail.resolve(Response.json({ ...envelope, project, task: { ...taskDetail, ...updatedTask } }));
  await waitFor(() => assert.equal(Boolean(within(inspector).queryByRole("button", { name: "Accept" })), false));
});

test("Request changes submits one bounded review note and resets the review editor", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const alpha = { ...task, assigned_agent_id: "agent_alpha", workflow_stage: "review" as const };
  const updatedTask = { ...task, revision: 2, workflow_stage: "planned" as const, planning_state: "planned" as const };
  const updated = { ...updatedTask, assigned_agent_id: "agent_alpha" };
  const reviewAttempt = { agent_id: "agent_alpha", completed_at: "2026-08-30T12:00:00Z", completion_reason: null, created_at: "2026-08-30T12:00:00Z", dispatch_state: "accepted", partial: false, review_action: null, review_note: null, review_task_revision: null, run_id: "run_alpha", runtime_type: "codex", state: "review_ready" as const, status: "completed", task_revision: 1, terminal_finalized: true, updated_at: "2026-08-30T12:00:00Z" };
  const initialExecution = { ...envelope, execution: { attempt_count: 1, attempts: [reviewAttempt], available: false, reason: "unavailable" as const, review: { available: true, run_id: "run_alpha" } }, task: alpha };
  const changedAttempt = { ...reviewAttempt, review_action: "request_changes" as const, review_note: "Please add the missing acceptance criteria.", review_task_revision: 1, state: "changes_requested" as const, task_revision: 2 };
  const changedExecution = { ...envelope, execution: { attempt_count: 1, attempts: [changedAttempt], available: true, reason: null, review: { available: false, run_id: null } }, task: updated };
  const reviewBodies: unknown[] = [];
  let changed = false;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: { ...taskDetail, ...(changed ? updated : alpha) } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_revision: changed ? updated.revision : alpha.revision });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(changed ? changedExecution : initialExecution);
    if (url.pathname.endsWith("/execution/review")) { reviewBodies.push(JSON.parse(String(init?.body))); changed = true; return Response.json({ ...changedExecution, action: "request_changes", duplicate: false }); }
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: updatedTask });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await user.click(await screen.findByRole("button", { name: "Request changes" }));
  const note = "Please add the missing acceptance criteria.";
  await user.type(screen.getByLabelText("Feedback for changes"), note);
  await user.click(screen.getByRole("button", { name: "Send change request" }));
  await screen.findByText(/Changes requested; the Task is planned for another Run\./u);
  assert.equal(screen.queryByLabelText("Feedback for changes"), null);
  assert.equal(reviewBodies.length, 1);
  const body = reviewBodies[0] as Record<string, unknown>;
  assert.equal(body.action, "request_changes");
  assert.equal(body.expected_revision, 1);
  assert.equal(body.note, note);
  assert.equal(typeof body.idempotency_key, "string");
});

test("a late review mutation cannot overwrite a Task selected from the dependency map", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ addEventListener: () => undefined, matches: true, removeEventListener: () => undefined }) });
  const alpha = { ...task, assigned_agent_id: "agent_alpha", workflow_stage: "review" as const };
  const beta = { ...task, assigned_agent_id: "agent_alpha", id: "task_beta", title: "Prepare Beta" };
  const betaList = { ...listTask, id: beta.id, title: beta.title, description_preview: "Prepare the Beta changes." };
  const reviewAttempt = { agent_id: "agent_alpha", completed_at: "2026-08-30T12:00:00Z", completion_reason: null, created_at: "2026-08-30T12:00:00Z", dispatch_state: "accepted", partial: false, review_action: null, review_note: null, review_task_revision: null, run_id: "run_alpha", runtime_type: "codex", state: "review_ready" as const, status: "completed", task_revision: 1, terminal_finalized: true, updated_at: "2026-08-30T12:00:00Z" };
  const alphaExecution = { ...envelope, execution: { attempt_count: 1, attempts: [reviewAttempt], available: false, reason: "unavailable" as const, review: { available: true, run_id: "run_alpha" } }, task: alpha };
  const betaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: beta };
  const lateMutation = deferred<Response>();
  const map = { ...dependencyMap, edge_count: 1, edge_total: 1, edges: [{ from_task_id: alpha.id, to_task_id: beta.id }], external_stub_count: 0, external_stub_total: 0, external_stubs: [], node_count: 2, node_total: 2, nodes: [{ ...dependencyMap.nodes[0], workflow_stage: "review" as const }, { blocked: false, id: beta.id, project_id: project.id, project_name: project.name, title: beta.title, workflow_stage: "planned" as const }] };
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, betaList] });
    if (url.pathname === "/api/agent-console/planning-dependency-map") { const { project_id, ...payload } = map; void project_id; return Response.json({ ...envelope, ...payload, project }); }
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, description: "Prepare the Beta changes." } : { ...taskDetail, ...alpha } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? alpha.id });
    if (url.pathname === "/api/agent-console/planning-task-execution") return Response.json(taskId === beta.id ? betaExecution : alphaExecution);
    if (url.pathname.endsWith("/execution/review")) return lateMutation.promise;
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: alpha });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await user.click(await screen.findByRole("button", { name: "Accept" }));
  await user.click(screen.getByRole("button", { name: "Map" }));
  await user.click(await screen.findByRole("button", { name: /Prepare Beta, Task, planned/u }));
  const inspector = screen.getByLabelText("Task inspector");
  await within(inspector).findByText("Prepare the Beta changes.");
  await within(inspector).findByRole("button", { name: "Run once" });
  lateMutation.resolve(Response.json({ ...envelope, action: "accept", duplicate: false, execution: { attempt_count: 1, attempts: [], available: false, reason: "unavailable", review: { available: false, run_id: null } }, task: { ...alpha, revision: 2, workflow_stage: "done", planning_state: "done", status: "completed" } }));
  await waitFor(() => {
    assert.match(within(inspector).getByText("Prepare the Beta changes.").textContent ?? "", /Beta changes/u);
    assert.ok(within(inspector).getByRole("button", { name: "Run once" }));
    assert.doesNotMatch(screen.getByRole("status").textContent ?? "", /Task accepted/u);
  });
});

test("moving an assigned Task to planned refreshes Run once availability", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const inboxTask = { ...task, planning_state: "inbox" as const, status: "todo" as const, workflow_stage: "inbox" as const };
  const inboxDetail = { ...taskDetail, ...inboxTask, assigned_agent_id: "agent_alpha" };
  const plannedTask = { ...inboxTask, planning_state: "planned" as const, revision: 2, workflow_stage: "planned" as const };
  const plannedDetail = { ...inboxDetail, ...plannedTask };
  const unavailableExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: false, reason: "unavailable", review: { available: false, run_id: null } }, task: { ...inboxTask, assigned_agent_id: "agent_alpha" } };
  const availableExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: { ...plannedTask, assigned_agent_id: "agent_alpha" } };
  let moved = false;
  let executionReads = 0;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [{ ...inboxTask, description_preview: listTask.description_preview }] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: moved ? plannedDetail : inboxDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_revision: moved ? plannedTask.revision : inboxTask.revision });
    if (url.pathname === "/api/agent-console/planning-task-execution") { executionReads += 1; return Response.json(moved ? availableExecution : unavailableExecution); }
    if (url.pathname === `/api/planning/tasks/${task.id}/edit`) {
      assert.equal(init?.method, "POST");
      moved = true;
      return Response.json({ ...envelope, action: "edit", project, task: plannedTask });
    }
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: plannedTask });
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await screen.findByText("Run once is unavailable for this Task.");
  const inspector = screen.getByLabelText("Task inspector");
  await user.click(within(inspector).getByRole("button", { name: "planned" }));
  await screen.findByRole("button", { name: "Run once" });
  assert.equal(executionReads, 2);
});

test("a late initial execution read cannot replace a newer stage refresh for the same Task", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const inboxTask = { ...task, planning_state: "inbox" as const, status: "todo" as const, workflow_stage: "inbox" as const };
  const plannedTask = { ...inboxTask, planning_state: "planned" as const, revision: 2, workflow_stage: "planned" as const };
  const unavailableExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: false, reason: "unavailable", review: { available: false, run_id: null } }, task: { ...inboxTask, assigned_agent_id: "agent_alpha" } };
  const availableExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: { ...plannedTask, assigned_agent_id: "agent_alpha" } };
  const initialExecution = deferred<Response>();
  let executionReads = 0;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [{ ...inboxTask, description_preview: listTask.description_preview }] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: { ...taskDetail, ...(executionReads > 1 ? plannedTask : inboxTask), assigned_agent_id: "agent_alpha" } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_revision: executionReads > 1 ? plannedTask.revision : inboxTask.revision });
    if (url.pathname === "/api/agent-console/planning-task-execution") { executionReads += 1; return executionReads === 1 ? initialExecution.promise : Response.json(availableExecution); }
    if (url.pathname === `/api/planning/tasks/${task.id}/edit`) { assert.equal(init?.method, "POST"); return Response.json({ ...envelope, action: "edit", project, task: plannedTask }); }
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: plannedTask });
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  const inspector = screen.getByLabelText("Task inspector");
  await user.click(within(inspector).getByRole("button", { name: "planned" }));
  await screen.findByRole("button", { name: "Run once" });
  initialExecution.resolve(Response.json(unavailableExecution));
  await waitFor(() => assert.ok(within(inspector).getByRole("button", { name: "Run once" })));
});

test("a late execution refresh cannot overwrite a newly selected Task", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const beta = { ...task, id: "task_beta", project_name: project.name, revision: 1, title: "Prepare Beta", workflow_stage: "planned" as const };
  const alphaPlanned = { ...task, revision: 2, workflow_stage: "planned" as const };
  const alphaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: false, reason: "unavailable", review: { available: false, run_id: null } }, task: { ...task, assigned_agent_id: "agent_alpha" } };
  const betaExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: { ...beta, assigned_agent_id: "agent_alpha" } };
  const lateAlphaRefresh = deferred<Response>();
  let alphaExecutionReads = 0;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    const taskId = url.searchParams.get("task_id");
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 2, next_cursor: null, project, tasks: [listTask, { ...beta, description_preview: "Prepare the Beta changes." }] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskId === beta.id ? { ...taskDetail, ...beta, assigned_agent_id: "agent_alpha", description: "Prepare the Beta changes." } : { ...taskDetail, ...(alphaExecutionReads > 1 ? alphaPlanned : task), assigned_agent_id: "agent_alpha" } });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, task_id: taskId ?? task.id, task_revision: taskId === beta.id ? beta.revision : alphaExecutionReads > 1 ? alphaPlanned.revision : task.revision });
    if (url.pathname === "/api/agent-console/planning-task-execution") {
      if (taskId === beta.id) return Response.json(betaExecution);
      alphaExecutionReads += 1;
      return alphaExecutionReads === 1 ? Response.json(alphaExecution) : lateAlphaRefresh.promise;
    }
    if (url.pathname === `/api/planning/tasks/${task.id}/edit`) { assert.equal(init?.method, "POST"); return Response.json({ ...envelope, action: "edit", project, task: alphaPlanned }); }
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: alphaPlanned });
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/u }));
  await screen.findByText("Run once is unavailable for this Task.");
  const inspector = screen.getByLabelText("Task inspector");
  await user.click(within(inspector).getByRole("button", { name: "inbox" }));
  await waitFor(() => assert.equal(alphaExecutionReads, 2));
  await user.click(screen.getByRole("button", { name: /Prepare Beta/u }));
  await within(inspector).findByText("Prepare the Beta changes.");
  await within(inspector).findByRole("button", { name: "Run once" });
  lateAlphaRefresh.resolve(Response.json({ ...envelope, execution: { ...alphaExecution.execution, available: false }, task: alphaPlanned }));
  await waitFor(() => {
    assert.match(within(inspector).getByText("Prepare the Beta changes.").textContent ?? "", /Prepare the Beta/u);
    assert.ok(within(inspector).getByRole("button", { name: "Run once" }));
  });
});

test("planning selectors stage locally and Apply is the only context mutation", async () => {
  const calls: Array<{ body?: string; method: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); const method = init?.method ?? "GET";
    calls.push({ body: init?.body?.toString(), method, path: url.pathname + url.search });
    if (url.pathname.endsWith("planning-tasks")) return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname.endsWith("planning-context") && method === "POST") return Response.json({ ...readyContext, action: "set", conversation });
    if (url.pathname.endsWith("planning-context")) return Response.json(readyContext);
    throw new Error(`${method} ${url.pathname}`);
  };
  function Harness() {
    const [selection, setSelection] = useState({ projectId: null as string | null, taskId: null as string | null });
    const [context, setContext] = useState<PublicConversationPlanningContext>(emptyContext);
    return <ConversationPlanningControls busy={false} clearDisabledReason={null} context={context} contextState="ready" conversationId="conv_plan" conversationRevision={1} disabledReason={null} onContext={setContext} onConversation={() => undefined} onNotice={() => undefined} onRefreshConversation={async () => undefined} onSelection={setSelection} overview={overview} overviewState="ready" selection={selection} />;
  }
  const user = userEvent.setup({ document: dom.window.document }); render(<Harness />);
  await user.click(screen.getByText("Planning context"));
  await user.selectOptions(screen.getByLabelText("Project planning context"), project.id);
  await waitFor(() => assert.equal((screen.getByLabelText("Task planning context") as HTMLSelectElement).disabled, false));
  await user.selectOptions(screen.getByLabelText("Task planning context"), task.id);
  assert.equal(calls.filter((call) => call.method !== "GET").length, 0);
  await user.click(screen.getByRole("button", { name: "Apply" }));
  await waitFor(() => assert.equal(calls.filter((call) => call.method === "POST").length, 1));
  assert.deepEqual(JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}"), { expected_revision: 1, project_id: project.id, task_id: task.id });
  assert.equal(calls.filter((call) => call.method === "GET" && call.path.includes("planning-context")).length, 0);
});

test("planning suggestions only fill a draft and attention remains navigation-only", async () => {
  let selected = ""; render(<><PlanningSuggestions context={readyContext} draftEmpty onChoose={(text) => { selected = text; }} /><PlanningAttention overview={overview} state="ready" /></>);
  const user = userEvent.setup({ document: dom.window.document }); await user.click(screen.getByRole("button", { name: "Plan next steps" }));
  assert.match(selected, /Ship Alpha/u);
  const link = screen.getByRole("link", { name: /Open Ship Alpha/u }) as HTMLAnchorElement;
  assert.equal(link.getAttribute("href"), "/tasks?project=project_alpha&task=task_alpha");
  assert.match(screen.getByText(/overdue/iu).textContent ?? "", /overdue/iu);
});

test("a stale context update refreshes canonical state and keeps the staged Project", async () => {
  const other = { id: "project_beta", name: "Beta", revision: 1, status: "active" as const };
  const staleOverview = { ...overview, project_count: 2, projects: [project, other] };
  let refreshed = false;
  let conversationRefreshed = false;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); const method = init?.method ?? "GET";
    if (url.pathname.endsWith("planning-tasks")) return Response.json({ ...envelope, count: 0, next_cursor: null, project: other, tasks: [] });
    if (url.pathname.endsWith("planning-context") && method === "POST") return Response.json({ schema_version: 1, status: "conflict" }, { status: 409 });
    if (url.pathname.endsWith("planning-context")) { refreshed = true; return Response.json(emptyContext); }
    throw new Error(`${method} ${url.pathname}`);
  };
  function Harness() {
    const [selection, setSelection] = useState({ projectId: null as string | null, taskId: null as string | null });
    return <ConversationPlanningControls busy={false} clearDisabledReason={null} context={emptyContext} contextState="ready" conversationId="conv_plan" conversationRevision={1} disabledReason={null} onContext={() => undefined} onConversation={() => undefined} onNotice={() => undefined} onRefreshConversation={async () => { conversationRefreshed = true; }} onSelection={setSelection} overview={staleOverview} overviewState="ready" selection={selection} />;
  }
  const user = userEvent.setup({ document: dom.window.document }); render(<Harness />);
  await user.click(screen.getByText("Planning context")); await user.selectOptions(screen.getByLabelText("Project planning context"), other.id);
  await user.click(screen.getByRole("button", { name: "Apply" })); await waitFor(() => assert.equal(refreshed, true));
  assert.equal(conversationRefreshed, true);
  assert.equal((screen.getByLabelText("Project planning context") as HTMLSelectElement).value, other.id);
});

test("stale context is explicit, suppresses suggestions, and an idle archive can Clear", async () => {
  const archivedConversation = { ...conversation, archived_at: "2026-08-30T12:00:00Z", revision: 3, state: "archived" as const };
  const staleContext = { ...readyContext, conversation_revision: 2, state: "task_unavailable" as const, task: null };
  const cleared = { ...emptyContext, action: "clear" as const, conversation: archivedConversation, conversation_revision: 3 };
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname.endsWith("planning-tasks")) return Response.json({ ...envelope, count: 0, next_cursor: null, project, tasks: [] });
    if (url.pathname.endsWith("planning-context") && init?.method === "POST") return Response.json(cleared);
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  function Harness() {
    const [context, setContext] = useState<PublicConversationPlanningContext>(staleContext);
    const [selection, setSelection] = useState({ projectId: project.id as string | null, taskId: task.id as string | null });
    return <><ConversationPlanningControls busy={false} clearDisabledReason={null} context={context} contextState="ready" conversationId="conv_plan" conversationRevision={2} disabledReason="Restore this Conversation before applying new planning context." onContext={setContext} onConversation={() => undefined} onNotice={() => undefined} onRefreshConversation={async () => undefined} onSelection={setSelection} overview={overview} overviewState="ready" selection={selection} /><PlanningSuggestions context={context} draftEmpty onChoose={() => undefined} /></>;
  }
  const user = userEvent.setup({ document: dom.window.document }); render(<Harness />);
  assert.match(screen.getByText("Task unavailable").textContent ?? "", /unavailable/u);
  assert.equal(screen.queryByLabelText("Planning prompt suggestions"), null);
  await user.click(screen.getByText("Planning context"));
  await screen.findByText(/saved planning reference is stale/u);
  assert.equal((screen.getByRole("button", { name: "Clear" }) as HTMLButtonElement).disabled, false);
  await user.click(screen.getByRole("button", { name: "Clear" }));
  await waitFor(() => assert.match(screen.getByText("No planning context").textContent ?? "", /No planning context/u));
});

test("Projects and Tasks deep-links, validates forms, and preserves failed input", async () => {
  dom.reconfigure({ url: `${origin}/tasks?task=${task.id}` });
  let projectCreateAttempts = 0; const calls: Array<{ body?: string; method: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); const method = init?.method ?? "GET"; calls.push({ body: init?.body?.toString(), method, path: url.pathname });
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agent-console/planning-task") return Response.json({ ...envelope, project, task: { ...task, attention_reasons: [] } });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskDetail });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [{ capabilities: [], id: "agent_alpha", name: "Alpha Agent", runtime_config_id: "config_alpha", runtime_type: "hermes" }], count: 1 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/projects" && method === "POST") { projectCreateAttempts += 1; return Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 }); }
    throw new Error(`${method} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await waitFor(() => assert.equal(document.activeElement?.getAttribute("data-planning-task-id"), task.id));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /Opened Task Ship Alpha/u));
  await user.click(screen.getByRole("button", { name: "New" }));
  const name = screen.getByLabelText("Name") as HTMLInputElement; await user.type(name, "New Project"); await user.click(screen.getByRole("button", { name: "Create Project" }));
  await waitFor(() => assert.equal(projectCreateAttempts, 1));
  assert.equal(name.value, "New Project");
  assert.match(screen.getByRole("status").textContent ?? "", /details were kept|name was kept/iu);
  assert.equal(calls.filter((call) => call.method === "POST").length, 1);
});

test("a missing deep-link Project is announced without hiding the Task list", async () => {
  dom.reconfigure({ url: `${origin}/tasks?project=project_missing&task=${task.id}` });
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json(overview);
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    throw new Error(`GET ${url.pathname}`);
  };
  render(<ProjectsTasksWorkspace />);
  await screen.findByText("Ship Alpha");
  assert.equal(screen.getByText("Ship the reviewed Alpha changes.").textContent, "Ship the reviewed Alpha changes.");
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /requested Project could not be found/u));
  const user = userEvent.setup({ document: dom.window.document });
  await user.click(screen.getByRole("button", { name: "Add" }));
  assert.equal((screen.getByLabelText("Agent") as HTMLSelectElement).disabled, true);
  assert.match(screen.getByText(/No Agents are available/u).textContent ?? "", /unassigned/u);
  await user.type(screen.getByLabelText("Title"), "Unassigned Task");
  assert.equal((screen.getByRole("button", { name: "Create Task" }) as HTMLButtonElement).disabled, false);
});

test("Add creates one Task inside the selected Project with only Title, Agent, and Due", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const calls: Array<{ body?: string; method: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); const method = init?.method ?? "GET"; calls.push({ body: init?.body?.toString(), method, path: url.pathname });
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json(overview);
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [{ capabilities: [], id: "agent_alpha", name: "Alpha Agent", runtime_config_id: "config_alpha", runtime_type: "hermes" }], count: 1 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 0, next_cursor: null, project, tasks: [] });
    if (url.pathname === `/api/projects/${project.id}/tasks` && method === "POST") return Response.json({ ...envelope, action: "create", project, task: { ...task, due_date: "2026-09-01", priority: "medium", title: "New Task" } }, { status: 201 });
    throw new Error(`${method} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await screen.findByRole("button", { name: "Add" }); await user.click(screen.getByRole("button", { name: "Add" }));
  await user.type(screen.getByLabelText("Title"), "New Task");
  assert.equal((screen.getByRole("button", { name: "Create Task" }) as HTMLButtonElement).disabled, false);
  await user.selectOptions(screen.getByLabelText("Agent"), "agent_alpha");
  fireEvent.change(screen.getByLabelText("Due"), { target: { value: "2026-09-01" } });
  await user.click(screen.getByRole("button", { name: "Create Task" }));
  await screen.findByText("New Task");
  const mutation = calls.find((call) => call.method === "POST");
  assert.equal(mutation?.path, `/api/projects/${project.id}/tasks`);
  assert.deepEqual(JSON.parse(mutation?.body ?? "{}"), { assigned_agent_id: "agent_alpha", due_date: "2026-09-01", title: "New Task" });
});

test("Projects render before optional Agent inventory settles", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const agents = deferred<Response>();
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json(overview);
    if (url.pathname === "/api/agents") return await agents.promise;
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    throw new Error(`GET ${url.pathname}`);
  };
  render(<ProjectsTasksWorkspace />);
  await screen.findByRole("button", { name: "Select Alpha Project" });
  agents.resolve(Response.json({ ...envelope, agents: [], count: 0 }));
});

test("Task paging paints the first page before resolving an exact deep link", async () => {
  const laterTask = { ...task, id: "task_later", title: "Later Task" };
  dom.reconfigure({ url: `${origin}/tasks?project=${project.id}&task=${laterTask.id}` });
  const laterPage = deferred<Response>();
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks" && !url.searchParams.has("cursor")) return Response.json({ ...envelope, count: 1, next_cursor: "next_page", project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-tasks") return await laterPage.promise;
    throw new Error(`GET ${url.pathname}`);
  };
  render(<ProjectsTasksWorkspace />);
  await screen.findByText("Ship Alpha");
  laterPage.resolve(Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [{ ...laterTask, description_preview: "Later Task description." }] }));
  await waitFor(() => assert.equal(document.activeElement?.getAttribute("data-planning-task-id"), laterTask.id));
});

test("a task-only locator resolved before overview keeps its exact Project", async () => {
  const beta = { id: "project_beta", name: "Beta", revision: 1, status: "active" as const };
  const betaTask = { ...task, id: "task_beta", project_id: beta.id, project_name: beta.name, title: "Beta Task" };
  const overviewRead = deferred<Response>(); const locatorRead = deferred<Response>();
  dom.reconfigure({ url: `${origin}/tasks?task=${betaTask.id}` });
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return await overviewRead.promise;
    if (url.pathname === "/api/agent-console/planning-task") return await locatorRead.promise;
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project: beta, tasks: [{ ...betaTask, description_preview: "Beta Task description." }] });
    throw new Error(`GET ${url.pathname}`);
  };
  render(<ProjectsTasksWorkspace />);
  locatorRead.resolve(Response.json({ ...envelope, project: beta, task: betaTask }));
  overviewRead.resolve(Response.json({ ...overview, attention: [], attention_count: 0, project_count: 2, projects: [project, beta] }));
  await screen.findByRole("heading", { name: "Beta" });
  assert.equal(screen.getByRole("button", { name: "Select Beta Project" }).getAttribute("aria-current"), "true");
});

test("manual Project selection wins over a late task-only locator", async () => {
  const beta = { id: "project_beta", name: "Beta", revision: 1, status: "active" as const };
  const betaTask = { ...task, id: "task_beta", project_id: beta.id, project_name: beta.name, title: "Beta Task" };
  const locatorRead = deferred<Response>();
  dom.reconfigure({ url: `${origin}/tasks?task=${betaTask.id}` });
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0, project_count: 2, projects: [project, beta] });
    if (url.pathname === "/api/agent-console/planning-task") return await locatorRead.promise;
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 0, next_cursor: null, project: url.searchParams.get("project_id") === beta.id ? beta : project, tasks: [] });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await screen.findByRole("button", { name: "Select Alpha Project" });
  await user.click(screen.getByRole("button", { name: "Select Alpha Project" }));
  locatorRead.resolve(Response.json({ ...envelope, project: beta, task: betaTask }));
  await new Promise((resolve) => window.setTimeout(resolve, 20));
  assert.equal(screen.getByRole("button", { name: "Select Alpha Project" }).getAttribute("aria-current"), "true");
});

test("switching Projects closes a staged Task form before submission", async () => {
  const beta = { id: "project_beta", name: "Beta", revision: 1, status: "active" as const };
  dom.reconfigure({ url: `${origin}/tasks` });
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, project_count: 2, projects: [project, beta] });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 0, next_cursor: null, project: url.searchParams.get("project_id") === beta.id ? beta : project, tasks: [] });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await screen.findByRole("button", { name: "Add" }); await user.click(screen.getByRole("button", { name: "Add" }));
  await user.type(screen.getByLabelText("Title"), "Bound to Alpha");
  await user.click(screen.getByRole("button", { name: "Select Beta Project" }));
  assert.equal(screen.queryByLabelText("Title"), null);
  assert.equal(screen.queryByRole("button", { name: "Create Task" }), null);
});

test("archived Projects are an explicit planner view with a deliberate restore path", async () => {
  const archived = { id: "project_archive", name: "Archive", revision: 3, status: "archived" as const };
  let restored = false;
  dom.reconfigure({ url: `${origin}/tasks` });
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin);
    const visibleArchive = restored ? { ...archived, revision: 4, status: "active" as const } : archived;
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0, project_count: 2, projects: [project, visibleArchive] });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") {
      const selected = url.searchParams.get("project_id") === archived.id ? visibleArchive : project;
      return Response.json({ ...envelope, count: 0, next_cursor: null, project: selected, tasks: [] });
    }
    if (url.pathname === `/api/planning/projects/${archived.id}/restore` && init?.method === "POST") {
      restored = true;
      return Response.json({ ...envelope, action: "restore", project: { ...archived, revision: 4, status: "active" } });
    }
    throw new Error(`${init?.method ?? "GET"} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await screen.findByRole("button", { name: "Select Alpha Project" });
  assert.equal(screen.queryByRole("button", { name: "Select Archive Project" }), null);
  await user.click(screen.getByRole("button", { name: "Archived Projects" }));
  await screen.findByRole("button", { name: "Select Archive Project" });
  assert.equal(screen.queryByRole("button", { name: "Select Alpha Project" }), null);
  await user.click(screen.getByRole("button", { name: "Restore Project" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /Project restored/u));
  assert.equal((screen.getByRole("button", { name: "Active Projects" }) as HTMLButtonElement).getAttribute("aria-pressed"), "true");
  assert.equal(screen.getByRole("button", { name: "Select Archive Project" }).getAttribute("aria-current"), "true");
});

test("an empty archived Project view gives the planner a recovery action", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 0, next_cursor: null, project, tasks: [] });
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await screen.findByRole("button", { name: "Select Alpha Project" });
  await user.click(screen.getByRole("button", { name: "Archived Projects" }));
  await screen.findByText("No archived Projects.");
  await user.click(screen.getByRole("button", { name: "Show active Projects" }));
  await screen.findByRole("button", { name: "Select Alpha Project" });
  assert.equal((screen.getByRole("button", { name: "Active Projects" }) as HTMLButtonElement).getAttribute("aria-pressed"), "true");
});

test("Task detail editing stages accessible cross-Project dependencies in one save", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const calls: Array<{ body?: string; method: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); const method = init?.method ?? "GET"; calls.push({ body: init?.body?.toString(), method, path: url.pathname });
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === "/api/agent-console/planning-dependency-picker") return Response.json(picker);
    if (url.pathname === `/api/planning/tasks/${task.id}/edit` && method === "POST") return Response.json({ ...envelope, action: "edit", project, task: { ...task, revision: 2 } });
    throw new Error(`${method} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/ }));
  await screen.findByRole("button", { name: "Edit details" }); await user.click(screen.getByRole("button", { name: "Edit details" }));
  await screen.findByText("Dependents (1)");
  assert.match(screen.getAllByText(/Prepare Beta · Project: Beta/u)[0]?.textContent ?? "", /planned/u);
  await user.click(screen.getByRole("button", { name: "Add prerequisite Prepare Beta" }));
  await user.click(screen.getByRole("button", { name: "Save details" }));
  await waitFor(() => assert.equal(calls.filter((call) => call.method === "POST").length, 1));
  const mutation = calls.find((call) => call.method === "POST");
  assert.deepEqual(JSON.parse(mutation?.body ?? "{}").changes.depends_on, [dependency.id]);
});

test("stale dependency picker pages cannot replace the current search", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const alphaMore = deferred<Response>();
  const rejectedAlphaMore = deferred<Response>();
  let alphaMoreRequests = 0;
  const alpha = { ...dependency, id: "task_alpha_choice", project_name: "Alpha", title: "Alpha prerequisite" };
  const laterAlpha = { ...dependency, id: "task_later_alpha", project_name: "Alpha", title: "Later Alpha prerequisite" };
  const beta = { ...dependency, id: "task_beta_choice", title: "Beta prerequisite" };
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === "/api/agent-console/planning-dependency-picker") {
      const query = url.searchParams.get("q") ?? "";
      const cursor = url.searchParams.get("cursor");
      if (query === "Alpha" && cursor === "cursor_alpha") { alphaMoreRequests += 1; return alphaMoreRequests === 1 ? alphaMore.promise : rejectedAlphaMore.promise; }
      if (query === "Alpha") return Response.json({ ...picker, candidates: [alpha], match_count: 2, next_cursor: "cursor_alpha", query, truncated: true });
      if (query === "Beta") return Response.json({ ...picker, candidates: [beta], match_count: 1, next_cursor: null, query, truncated: false });
      return Response.json(picker);
    }
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/ }));
  await user.click(await screen.findByRole("button", { name: "Edit details" }));
  const search = await screen.findByPlaceholderText("Search Tasks");
  await user.type(search, "Alpha");
  await screen.findByText(/Alpha prerequisite/u);
  await user.click(screen.getByRole("button", { name: "More Task choices" }));
  await user.clear(search); await user.type(search, "Beta");
  await screen.findByText(/Beta prerequisite/u);
  alphaMore.resolve(Response.json({ ...picker, candidates: [laterAlpha], match_count: 2, next_cursor: null, query: "Alpha", truncated: false }));
  await waitFor(() => assert.equal(screen.queryByText(/Later Alpha prerequisite/u), null));
  assert.equal(screen.queryByRole("button", { name: "More Task choices" }), null);
  await user.clear(search); await user.type(search, "Alpha");
  await screen.findByText(/Alpha prerequisite/u);
  await user.click(screen.getByRole("button", { name: "More Task choices" }));
  await user.clear(search); await user.type(search, "Beta");
  await screen.findByText(/Beta prerequisite/u);
  rejectedAlphaMore.reject(new Error("stale request"));
  await waitFor(() => assert.equal(screen.queryByText("Task choices are temporarily unavailable."), null));
  assert.notEqual(screen.queryByText(/Beta prerequisite/u), null);
});

test("dependency editor prevents saves beyond the 100-prerequisite boundary", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const prerequisites = Array.from({ length: 100 }, (_, index) => ({ ...dependency, id: `task_dependency_${index}`, title: `Prerequisite ${index}` }));
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: taskDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json({ ...dependencies, prerequisite_count: 100, prerequisites });
    if (url.pathname === "/api/agent-console/planning-dependency-picker") return Response.json(picker);
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/ }));
  await user.click(await screen.findByRole("button", { name: "Edit details" }));
  await screen.findByText(/Maximum of 100 prerequisites reached/u);
  assert.equal((screen.getByRole("button", { name: "Add prerequisite Prepare Beta" }) as HTMLButtonElement).disabled, true);
  assert.equal((screen.getByPlaceholderText("Search Tasks") as HTMLInputElement).maxLength, 160);
});

test("Task deletion shows only count effects, then confirms the exact preview before refreshing authority", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const reminderDetail = { ...taskDetail, reminders: [{ at: "2030-09-03T09:00:00Z", channel: "browser" as const, enabled: true, id: "reminder_delete" }] };
  const deletionPreview = { ...envelope, affected: { artifacts: 0, conversations: 1, projects: 0, runs: 1, tasks: 2 }, confirmation_id: "a".repeat(64), has_active_runs: true, target_id: task.id, target_kind: "task" as const };
  const deletion = { ...envelope, action: "delete" as const, deletion: deletionPreview.affected, target_id: task.id, target_kind: "task" as const };
  const calls: Array<{ body: unknown; path: string }> = [];
  let deleted = false;
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); const path = `${url.pathname}${url.search}`;
    calls.push({ body: init?.body ? JSON.parse(String(init.body)) : null, path });
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json(deleted ? { ...overview, attention: [], attention_count: 0, project_count: 0, projects: [] } : { ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: reminderDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === `/api/planning/tasks/${task.id}/delete/preview`) return Response.json(deletionPreview);
    if (url.pathname === `/api/planning/tasks/${task.id}/delete`) { deleted = true; return Response.json(deletion); }
    return Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 });
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/ }));
  await waitFor(() => assert.notEqual(nextBrowserTaskReminderDelay(Date.parse("2026-09-02T12:00:00Z")), null));
  await user.click(await screen.findByRole("button", { name: "Delete Task" }));
  await screen.findByText(/Delete 0 Projects, 2 Tasks, 1 Conversation, 1 Run, 0 artifacts/u);
  assert.match(screen.getByText(/Affected active Runs will be stopped/u).textContent ?? "", /nothing is removed/u);
  await user.click(screen.getByRole("button", { name: "Confirm delete Task" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /Deleted 0 Projects, 2 Tasks/u));
  assert.equal(nextBrowserTaskReminderDelay(Date.parse("2026-09-02T12:00:00Z")), null);
  assert.deepEqual(calls.filter((call) => call.path.includes("/delete")), [
    { body: {}, path: `/api/planning/tasks/${task.id}/delete/preview` },
    { body: { confirmation_id: deletionPreview.confirmation_id, confirmed: true }, path: `/api/planning/tasks/${task.id}/delete` },
  ]);
});

test("Project deletion clears every local reminder schedule because a count-only cascade can span dependent Tasks", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const reminderDetail = { ...taskDetail, reminders: [{ at: "2030-09-03T09:00:00Z", channel: "browser" as const, enabled: true, id: "reminder_project_delete" }] };
  const deletionPreview = { ...envelope, affected: { artifacts: 0, conversations: 0, projects: 1, runs: 0, tasks: 2 }, confirmation_id: "b".repeat(64), has_active_runs: false, target_id: project.id, target_kind: "project" as const };
  const deletion = { ...envelope, action: "delete" as const, deletion: deletionPreview.affected, target_id: project.id, target_kind: "project" as const };
  let deleted = false;
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json(deleted ? { ...overview, attention: [], attention_count: 0, project_count: 0, projects: [] } : { ...overview, attention: [], attention_count: 0 });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-task-detail") return Response.json({ ...envelope, project, task: reminderDetail });
    if (url.pathname === "/api/agent-console/planning-task-dependencies") return Response.json(dependencies);
    if (url.pathname === `/api/planning/projects/${project.id}/delete/preview`) return Response.json(deletionPreview);
    if (url.pathname === `/api/planning/projects/${project.id}/delete`) { deleted = true; return Response.json(deletion); }
    return Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 });
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await user.click(await screen.findByRole("button", { name: /Ship Alpha/ }));
  await waitFor(() => assert.notEqual(nextBrowserTaskReminderDelay(Date.parse("2026-09-02T12:00:00Z")), null));
  await user.click(screen.getByRole("button", { name: "Delete Project" }));
  await screen.findByText(/Delete 1 Project, 2 Tasks, 0 Conversations, 0 Runs, 0 artifacts/u);
  await user.click(screen.getByRole("button", { name: "Confirm delete Project" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /Deleted 1 Project, 2 Tasks/u));
  assert.equal(nextBrowserTaskReminderDelay(Date.parse("2026-09-02T12:00:00Z")), null);
});

test("planning navigation search debounces typing and leaves selection unchanged until its uniquely named Open action", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const betaProject = { id: "project_beta", name: "Beta", revision: 1, status: "active" as const };
  const searches: string[] = [];
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return Response.json({ ...overview, attention: [], attention_count: 0, project_count: 2, projects: [project, betaProject] });
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-search") {
      const query = url.searchParams.get("q") ?? ""; searches.push(query);
      return Response.json({ ...envelope, project_count: 1, projects: [{ id: betaProject.id, title: betaProject.name, type: "project" as const }], query, task_count: 1, tasks: [{ id: "task_beta", title: "Prepare Beta", type: "task" as const }], truncated: false });
    }
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await screen.findByText("Ship Alpha");
  const search = screen.getByPlaceholderText("Find a Project or Task");
  await user.type(search, "Be"); await user.type(search, "ta");
  await screen.findByRole("button", { name: "Open Project Beta" });
  assert.deepEqual(searches, ["Beta"]);
  assert.ok(screen.getByRole("button", { name: "Open Task Prepare Beta" }));
  assert.equal(screen.getByRole("button", { name: "Select Alpha Project" }).getAttribute("aria-current"), "true");
  assert.equal(window.location.search, "");
});

test("a stale planning search Project result retains the selected Project and URL", async () => {
  dom.reconfigure({ url: `${origin}/tasks` });
  const betaProject = { id: "project_beta", name: "Beta", revision: 1, status: "active" as const };
  let overviewReads = 0;
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") {
      overviewReads += 1;
      return Response.json(overviewReads === 1 ? { ...overview, attention: [], attention_count: 0 } : { ...overview, attention: [], attention_count: 0 });
    }
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] });
    if (url.pathname === "/api/agent-console/planning-search") {
      const query = url.searchParams.get("q") ?? "";
      return Response.json({ ...envelope, project_count: 1, projects: [{ id: betaProject.id, title: betaProject.name, type: "project" as const }], query, task_count: 0, tasks: [], truncated: false });
    }
    throw new Error(`GET ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await screen.findByText("Ship Alpha");
  await user.type(screen.getByPlaceholderText("Find a Project or Task"), "Beta");
  await user.click(await screen.findByRole("button", { name: "Open Project Beta" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /no longer available/u));
  assert.equal(screen.getByRole("button", { name: "Select Alpha Project" }).getAttribute("aria-current"), "true");
  assert.equal(window.location.search, "");
});
