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

const { cleanup, fireEvent, render, screen, waitFor } = await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { ConversationPlanningControls, PlanningAttention, PlanningSuggestions } = await import("../src/app/conversation-planning.tsx");
const { ProjectsTasksWorkspace } = await import("../src/app/tasks/projects-tasks-workspace.tsx");

const envelope = { runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" } as const;
const project = { id: "project_alpha", name: "Alpha", status: "active" as const };
const task = { attention_reasons: ["overdue" as const], due_date: "2026-08-29", id: "task_alpha", needs_attention: true, planned_for_today: false, planning_state: "planned" as const, priority: "high" as const, project_id: project.id, project_name: project.name, review_required: false, status: "todo" as const, title: "Ship Alpha", updated_at: "2026-08-29T12:00:00Z" };
const overview = { ...envelope, attention: [task], attention_count: 1, project_count: 1, projects: [project], today: "2026-08-30", truncated: false };
const emptyContext = { ...envelope, association: null, conversation_id: "conv_plan", conversation_revision: 1, project: null, state: "empty" as const, task: null };
const readyContext = { ...envelope, association: { project_id: project.id, task_id: task.id }, conversation_id: "conv_plan", conversation_revision: 2, project, state: "ready" as const, task };
const conversation = { agent_id: "agent_alpha", archived_at: null, created_at: "2026-08-29T12:00:00Z", id: "conv_plan", revision: 2, state: "active" as const, title: "Plan", title_source: "manual" as const, updated_at: "2026-08-29T12:01:00Z" };
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; }

afterEach(() => cleanup());

test("planning selectors stage locally and Apply is the only context mutation", async () => {
  const calls: Array<{ body?: string; method: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), origin); const method = init?.method ?? "GET";
    calls.push({ body: init?.body?.toString(), method, path: url.pathname + url.search });
    if (url.pathname.endsWith("planning-tasks")) return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [task] });
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
  const other = { id: "project_beta", name: "Beta", status: "active" as const };
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
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [{ capabilities: [], id: "agent_alpha", name: "Alpha Agent", runtime_config_id: "config_alpha", runtime_type: "hermes" }], count: 1 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [task] });
    if (url.pathname === "/api/projects" && method === "POST") { projectCreateAttempts += 1; return Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 }); }
    throw new Error(`${method} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document }); render(<ProjectsTasksWorkspace />);
  await waitFor(() => assert.equal(document.activeElement?.getAttribute("data-planning-task-id"), task.id));
  assert.match(screen.getByRole("status").textContent ?? "", /Opened Task Ship Alpha/u);
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
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [task] });
    throw new Error(`GET ${url.pathname}`);
  };
  render(<ProjectsTasksWorkspace />);
  await screen.findByText("Ship Alpha");
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
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [task] });
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
    if (url.pathname === "/api/agent-console/planning-tasks" && !url.searchParams.has("cursor")) return Response.json({ ...envelope, count: 1, next_cursor: "next_page", project, tasks: [task] });
    if (url.pathname === "/api/agent-console/planning-tasks") return await laterPage.promise;
    throw new Error(`GET ${url.pathname}`);
  };
  render(<ProjectsTasksWorkspace />);
  await screen.findByText("Ship Alpha");
  laterPage.resolve(Response.json({ ...envelope, count: 1, next_cursor: null, project, tasks: [laterTask] }));
  await waitFor(() => assert.equal(document.activeElement?.getAttribute("data-planning-task-id"), laterTask.id));
});

test("a task-only locator resolved before overview keeps its exact Project", async () => {
  const beta = { id: "project_beta", name: "Beta", status: "active" as const };
  const betaTask = { ...task, id: "task_beta", project_id: beta.id, project_name: beta.name, title: "Beta Task" };
  const overviewRead = deferred<Response>(); const locatorRead = deferred<Response>();
  dom.reconfigure({ url: `${origin}/tasks?task=${betaTask.id}` });
  globalThis.fetch = async (input) => {
    const url = new URL(input.toString(), origin);
    if (url.pathname === "/api/agent-console/planning-overview") return await overviewRead.promise;
    if (url.pathname === "/api/agent-console/planning-task") return await locatorRead.promise;
    if (url.pathname === "/api/agents") return Response.json({ ...envelope, agents: [], count: 0 });
    if (url.pathname === "/api/agent-console/planning-tasks") return Response.json({ ...envelope, count: 1, next_cursor: null, project: beta, tasks: [betaTask] });
    throw new Error(`GET ${url.pathname}`);
  };
  render(<ProjectsTasksWorkspace />);
  locatorRead.resolve(Response.json({ ...envelope, project: beta, task: betaTask }));
  overviewRead.resolve(Response.json({ ...overview, attention: [], attention_count: 0, project_count: 2, projects: [project, beta] }));
  await screen.findByRole("heading", { name: "Beta" });
  assert.equal(screen.getByRole("button", { name: "Select Beta Project" }).getAttribute("aria-current"), "true");
});

test("manual Project selection wins over a late task-only locator", async () => {
  const beta = { id: "project_beta", name: "Beta", status: "active" as const };
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
  const beta = { id: "project_beta", name: "Beta", status: "active" as const };
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
