import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
import { useState } from "react";
import type { PlanDraft } from "../src/app/tasks/project-plan-editor.tsx";

const origin = "http://127.0.0.1:8890", projectId = "project_garage", agentId = "agent_research";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: `${origin}/tasks`, pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { cleanup, fireEvent, render, screen, waitFor } = await import("@testing-library/react");
const { ProjectPlanEditor } = await import("../src/app/tasks/project-plan-editor.tsx");
const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });
const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready" };
const project = { id: projectId, name: "Garage", revision: 1, status: "active" };
const contextId = `project_context_${"a".repeat(32)}`;
const agents = [{ id: agentId, name: "Research Agent", runtime_type: "codex", runtime_config_id: "config_research", capabilities: ["run.start"] }];
const emptyComparison = { missing_from_plan: [], additional_in_plan: [], missing_count: 0, additional_count: 0, truncated: false };
function task(id: string, title: string) { return { id, title, project_id: projectId, project_name: "Garage", status: "todo", priority: "medium", due_date: null,
  planned_for_today: false, planning_state: null, needs_attention: false, review_required: false, attention_reasons: [], updated_at: "2026-09-24T10:00:00Z",
  workflow_stage: "planned", deferred: false, blocked: false, revision: 1, description_preview: "" }; }
const research = task("task_research", "Research storage"), layout = task("task_layout", "Draw garage layout");
function inputEditor(id: string, title: string, grantRevision = 1) {
  const inputId = `task_input_${id === research.id ? "b".repeat(32) : "c".repeat(32)}`;
  const version = { id: inputId, revision: 1, task_revision: 1, agent_id: agentId, context_id: contextId, context_revision: 1,
    project_brief: "Garage goals", grant_revision: 1, instructions: "", created_at: 1790035200, files: [] };
  return { task: { id, title, revision: 1, project_id: projectId, project_status: "active", assigned_agent_id: agentId }, input_revision: 1,
    expected_task_token: "f".repeat(64), version, versions: [{ id: inputId, revision: 1, context_id: contextId, created_at: 1790035200 }],
    eligible_contexts: [{ context: { id: contextId, revision: 1, brief: "Garage goals", created_at: 1790035200, project_id: projectId,
      retired: false, current: true, files: [], prune_blocked: "current_version" }, grant_revision: grantRevision }] };
}
function fixture() {
  const calls: Array<{ path: string; body: Record<string, unknown> | null }> = [];
  const state = { calls, pageTwo: false, lostResponse: false, failBeforeSave: false, failReadback: false,
    holdPublish: false, releasePublish: null as null | (() => void),
    canonicalLayoutAfterResearch: false, historicalTaskChanged: false, grantRevision: 1,
    saved: null as null | { id: string; revision: number; title: string; nodes: Array<Record<string, unknown>> }, opened: [] as string[] };
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), origin), path = url.pathname;
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null;
    calls.push({ path, body });
    if (path === `/api/projects/${projectId}/plan` && init?.method === "POST") {
      if (state.holdPublish) await new Promise<void>((resolve) => { state.releasePublish = resolve; });
      if (state.failBeforeSave) return Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 });
      const revision = (state.saved?.revision ?? 0) + 1, id = `plan_version_${String(revision).repeat(32)}`;
      const nodes = (body!.nodes as Array<Record<string, unknown>>).map(({ expected_task_revision, ...node }) => ({ ...node, task_revision: expected_task_revision }));
      state.saved = { id, revision, title: body!.title as string, nodes };
      if (state.lostResponse) return Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 });
      return Response.json({ id, revision, project_id: projectId, status: "unapproved" });
    }
    if (path === `/api/projects/${projectId}/plan`) return state.failReadback && state.saved
      ? Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 }) : Response.json({ project, plan_revision: state.saved?.revision ?? 0,
      current: state.saved ? { title: state.saved.title, nodes: state.saved.nodes } : null,
      versions: state.saved ? [{ id: state.saved.id, revision: state.saved.revision, title: state.saved.title, node_count: state.saved.nodes.length, created_at: 1790035200 }] : [],
      stale_reasons: [], dependency_comparison: emptyComparison, execution_available: false });
    if (path.startsWith(`/api/projects/${projectId}/plan/`)) {
      if (!state.saved || path.split("/").at(-1) !== state.saved.id) return Response.json({ schema_version: 1, status: "version_unavailable" }, { status: 404 });
      return Response.json({ id: state.saved.id, project_id: projectId, revision: state.saved.revision, project_revision: 1, title: state.saved.title,
        nodes: state.saved.nodes.map((node) => ({ ...node,
          task_state: state.historicalTaskChanged ? "changed" : "current",
          task_title: state.historicalTaskChanged ? null : node.task_id === research.id ? research.title : layout.title,
          agent_state: "current", agent_name: "Research Agent" })),
        created_at: 1790035200, current: true, status: "unapproved" });
    }
    if (path === "/api/agent-console/planning-tasks") {
      const second = url.searchParams.has("cursor");
      return Response.json({ ...envelope, project, count: second ? 1 : 1, tasks: [second ? layout : research], next_cursor: second ? null : state.pageTwo ? "eA" : null });
    }
    if (path.startsWith("/api/planning/tasks/") && path.endsWith("/inputs")) {
      const id = path.split("/")[4];
      return Response.json(inputEditor(id, id === research.id ? research.title : layout.title, state.grantRevision));
    }
    if (path === "/api/agent-console/planning-task-dependencies") {
      const id = url.searchParams.get("task_id")!;
      const prerequisites = state.canonicalLayoutAfterResearch && id === layout.id ? [{ id: research.id, title: research.title, project_id: projectId,
        project_name: "Garage", workflow_stage: "planned", blocked: false }] : [];
      return Response.json({ ...envelope, task_id: id, task_revision: 1, prerequisites, prerequisite_count: prerequisites.length, prerequisites_truncated: false,
        dependents: [], dependent_count: 0, dependents_truncated: false });
    }
    throw new Error(`Unexpected request ${path}`);
  };
  return state;
}
function Workspace({ state }: { state: ReturnType<typeof fixture> }) {
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  return <ProjectPlanEditor projectId={projectId} agents={agents} draft={draft} onDraftChange={(update) => setDraft((current) => update(current))}
    onOpenTask={(id) => state.opened.push(id)} />;
}
async function open(state: ReturnType<typeof fixture>) {
  render(<Workspace state={state} />);
  fireEvent.click(screen.getByRole("button", { name: "Open plan" }));
  await screen.findByRole("button", { name: "Create plan" });
}

test("owner saves one exact prepared Task without starting an Agent", async () => {
  const state = fixture(); await open(state);
  fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
  fireEvent.change(screen.getByLabelText("Plan title"), { target: { value: "Garage organization" } });
  fireEvent.click(screen.getByRole("button", { name: "Add Research storage" }));
  await screen.findByText("Current Task inputs match this plan.");
  fireEvent.click(screen.getByRole("button", { name: "Review Task dependencies" }));
  await screen.findByText("Plan and canonical Task prerequisites match.");
  fireEvent.click(screen.getByRole("button", { name: "Save plan version" }));
  await screen.findByText("Plan version saved. It remains unapproved and cannot start Agent work.");
  assert.equal(state.saved?.title, "Garage organization");
  assert.equal(screen.queryByLabelText("Plan draft"), null);
  assert.equal(state.calls.some((call) => /run|dispatch|kanban|approve/u.test(call.path)), false);
});

test("later-page Task and stale regrant remain explicit", async () => {
  const state = fixture(); state.pageTwo = true; state.grantRevision = 2; await open(state);
  fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
  fireEvent.click(screen.getByRole("button", { name: "Load more Project Tasks" }));
  fireEvent.click(await screen.findByRole("button", { name: "Add Draw garage layout" }));
  await screen.findByText(/needs a current Agent assignment/u);
  assert.equal(screen.getByLabelText("Planned Tasks").querySelectorAll("li").length, 0);
  assert.equal(state.calls.some((call) => call.path.endsWith("/plan") && call.body), false);
});

test("lost save response preserves unresolved draft until explicit current-version review", async () => {
  const state = fixture(); state.lostResponse = true; await open(state);
  fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
  fireEvent.change(screen.getByLabelText("Plan title"), { target: { value: "Garage organization" } });
  fireEvent.click(screen.getByRole("button", { name: "Add Research storage" }));
  await screen.findByText("Current Task inputs match this plan.");
  fireEvent.click(screen.getByRole("button", { name: "Review Task dependencies" }));
  await screen.findByText("Plan and canonical Task prerequisites match.");
  fireEvent.click(screen.getByRole("button", { name: "Save plan version" }));
  await screen.findByText(/A save may have reached Mentat/u);
  assert.equal((screen.getByRole("button", { name: "Save plan version" }) as HTMLButtonElement).disabled, true);
  assert.equal(state.saved?.revision, 1);
  fireEvent.click(screen.getByRole("button", { name: "Refresh plan" }));
  fireEvent.click(await screen.findByRole("button", { name: "View version 1" }));
  await screen.findByRole("button", { name: "Use reviewed saved plan" });
  fireEvent.click(screen.getByRole("button", { name: "Use reviewed saved plan" }));
  assert.equal(screen.queryByLabelText("Plan draft"), null);
  assert.equal(state.calls.filter((call) => call.path.endsWith("/plan") && call.body).length, 1);
});

test("two-Task plan shows checkpoint and canonical dependency differences before Save", async () => {
  const state = fixture(); state.pageTwo = true; state.canonicalLayoutAfterResearch = true; await open(state);
  fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
  fireEvent.change(screen.getByLabelText("Plan title"), { target: { value: "Research then layout" } });
  fireEvent.click(screen.getByRole("button", { name: "Add Research storage" }));
  await screen.findByText("Current Task inputs match this plan.");
  fireEvent.click(screen.getByRole("button", { name: "Load more Project Tasks" }));
  fireEvent.click(await screen.findByRole("button", { name: "Add Draw garage layout" }));
  await waitFor(() => assert.equal(screen.getByLabelText("Planned Tasks").querySelectorAll("li.project-plan-node").length, 2));
  fireEvent.click(screen.getAllByRole("button", { name: "Add checkpoint before" })[1]);
  await screen.findByText(/Add the owner checkpoint before Draw garage layout/u);
  fireEvent.click(screen.getByRole("button", { name: "Apply plan edit" }));
  assert.match(screen.getByLabelText("Planned Tasks").textContent ?? "", /Checkpoint segment 1 · owner review/u);
  fireEvent.click(screen.getByRole("button", { name: "Review Task dependencies" }));
  await screen.findByText(/Canonical Task prerequisites missing from this plan: 1/u);
  assert.equal((screen.getByRole("button", { name: "Save plan version" }) as HTMLButtonElement).disabled, true);
  fireEvent.click(screen.getByRole("button", { name: "I reviewed these differences" }));
  fireEvent.click(screen.getByRole("button", { name: "Save plan version" }));
  await screen.findByText("Plan version saved. It remains unapproved and cannot start Agent work.");
  assert.equal(state.saved?.nodes.length, 2);
  assert.equal(state.saved?.nodes[1].segment, 1);
});

test("removing a prerequisite previews link repair before changing the draft", async () => {
  const state = fixture(); state.pageTwo = true; await open(state);
  fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
  fireEvent.click(screen.getByRole("button", { name: "Add Research storage" }));
  await screen.findByText("Current Task inputs match this plan.");
  fireEvent.click(screen.getByRole("button", { name: "Load more Project Tasks" }));
  fireEvent.click(await screen.findByRole("button", { name: "Add Draw garage layout" }));
  await waitFor(() => assert.equal(screen.getByLabelText("Planned Tasks").querySelectorAll("li.project-plan-node").length, 2));
  fireEvent.click(screen.getByLabelText("Research storage", { selector: "input" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Remove Task" })[0]);
  await screen.findByText(/remove 1 prerequisite link/u);
  assert.equal(screen.getByLabelText("Planned Tasks").querySelectorAll("li.project-plan-node").length, 2);
  fireEvent.click(screen.getByRole("button", { name: "Apply plan edit" }));
  assert.equal(screen.getByLabelText("Planned Tasks").querySelectorAll("li.project-plan-node").length, 1);
  assert.equal(state.calls.some((call) => call.path.endsWith("/plan") && call.body), false);
});

test("verified write with failed readback keeps the exact draft for reconciliation", async () => {
  const state = fixture(); await open(state);
  fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
  fireEvent.change(screen.getByLabelText("Plan title"), { target: { value: "Garage organization" } });
  fireEvent.click(screen.getByRole("button", { name: "Add Research storage" }));
  await screen.findByText("Current Task inputs match this plan.");
  fireEvent.click(screen.getByRole("button", { name: "Review Task dependencies" }));
  await screen.findByText("Plan and canonical Task prerequisites match.");
  state.failReadback = true;
  fireEvent.click(screen.getByRole("button", { name: "Save plan version" }));
  await screen.findByText(/readback is unavailable/u);
  assert.ok(screen.getByLabelText("Plan draft"));
  state.failReadback = false;
  fireEvent.click(screen.getByRole("button", { name: "Refresh plan" }));
  await screen.findByText("Plan version saved. It remains unapproved and cannot start Agent work.");
  assert.equal(screen.queryByLabelText("Plan draft"), null);
});

test("switching away and back preserves a local plan draft without publishing", async () => {
  const state = fixture();
  function Switching() {
    const [visible, setVisible] = useState(true), [draft, setDraft] = useState<PlanDraft | null>(null);
    return <><button onClick={() => setVisible(!visible)}>Switch Project</button>{visible ? <ProjectPlanEditor projectId={projectId} agents={agents}
      draft={draft} onDraftChange={(update) => setDraft((current) => update(current))} onOpenTask={(id) => state.opened.push(id)} /> : null}</>;
  }
  render(<Switching />);
  fireEvent.click(screen.getByRole("button", { name: "Open plan" }));
  fireEvent.click(await screen.findByRole("button", { name: "Create plan" }));
  fireEvent.change(screen.getByLabelText("Plan title"), { target: { value: "Keep the bike path open" } });
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" }));
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" }));
  fireEvent.click(screen.getByRole("button", { name: "Open plan" }));
  await screen.findByDisplayValue("Keep the bike path open");
  assert.equal(state.calls.some((call) => call.path.endsWith("/plan") && call.body), false);
});

test("in-flight Save freezes plan edits and a lost response remains unresolved", async () => {
  const state = fixture(); state.holdPublish = true; state.lostResponse = true; await open(state);
  fireEvent.click(screen.getByRole("button", { name: "Create plan" }));
  fireEvent.change(screen.getByLabelText("Plan title"), { target: { value: "Garage organization" } });
  fireEvent.click(screen.getByRole("button", { name: "Add Research storage" }));
  await screen.findByText("Current Task inputs match this plan.");
  fireEvent.click(screen.getByRole("button", { name: "Review Task dependencies" }));
  await screen.findByText("Plan and canonical Task prerequisites match.");
  fireEvent.click(screen.getByRole("button", { name: "Save plan version" }));
  await waitFor(() => assert.ok(state.releasePublish));
  assert.equal((screen.getByLabelText("Plan title") as HTMLInputElement).disabled, true);
  assert.equal((screen.getByLabelText("Attempts") as HTMLInputElement).disabled, true);
  assert.equal((screen.getByLabelText("Wall time (seconds)") as HTMLInputElement).disabled, true);
  state.releasePublish!();
  await screen.findByText(/A save may have reached Mentat/u);
  assert.equal((screen.getByRole("button", { name: "Save plan version" }) as HTMLButtonElement).disabled, true);
  assert.equal(state.calls.filter((call) => call.path.endsWith("/plan") && call.body).length, 1);
});

test("historical Task identity changes remain visible by ID", async () => {
  const state = fixture(); state.historicalTaskChanged = true;
  state.saved = { id: `plan_version_${"1".repeat(32)}`, revision: 1, title: "Garage history",
    nodes: [{ task_id: research.id, task_revision: 1, agent_id: agentId, input_version_id: `task_input_${"b".repeat(32)}`,
      after: [], segment: 0, max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 },
    { task_id: layout.id, task_revision: 1, agent_id: agentId, input_version_id: `task_input_${"c".repeat(32)}`,
      after: [research.id], segment: 1, max_attempts: 1, max_wall_seconds: 900, max_work_units: 100 }] };
  render(<Workspace state={state} />);
  fireEvent.click(screen.getByRole("button", { name: "Open plan" }));
  fireEvent.click(await screen.findByRole("button", { name: "View version 1" }));
  await screen.findByLabelText("Saved plan version");
  assert.match(screen.getByLabelText("Saved plan version").textContent ?? "", /task_research \(changed\)/u);
  assert.match(screen.getByLabelText("Saved plan version").textContent ?? "", /after task_research \(changed\)/u);
});
