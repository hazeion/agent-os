import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { JSDOM } from "jsdom";
import { useState } from "react";
import type { PublicConversationPlanningContext } from "../src/lib/public-planning.ts";

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

const { cleanup, fireEvent, render, screen, waitFor } = await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { ConversationPlanningControls, PlanningAttention, PlanningSuggestions } = await import("../src/app/conversation-planning.tsx");
const { ProjectsTasksWorkspace } = await import("../src/app/tasks/projects-tasks-workspace.tsx");
const { default: TaskDependencyMap, TaskDependencyMapFallback, layoutTaskDependencyMap } = await import("../src/app/tasks/task-dependency-map.tsx");

const envelope = { runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" } as const;
const project = { id: "project_alpha", name: "Alpha", revision: 1, status: "active" as const };
const task = { attention_reasons: ["overdue" as const], blocked: false, deferred: false, due_date: "2026-08-29", id: "task_alpha", needs_attention: true, planned_for_today: false, planning_state: "planned" as const, priority: "high" as const, project_id: project.id, project_name: project.name, review_required: false, revision: 1, status: "todo" as const, title: "Ship Alpha", updated_at: "2026-08-29T12:00:00Z", workflow_stage: "planned" as const };
const listTask = { ...task, description_preview: "Ship the reviewed Alpha changes." };
const taskDetail = { ...task, assigned_agent_id: null, description: "Ship the reviewed Alpha changes.", estimated_minutes: null, recurrence: null, subtasks: [], tags: [] };
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

afterEach(() => cleanup());

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
