import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgePlanningError,
  PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS,
  createBridgeProject,
  createBridgeProjectTask,
  fetchBridgeConversationPlanningContext,
  fetchBridgePlanningOverview,
  fetchBridgePlanningTask,
  fetchBridgePlanningTasks,
  updateBridgeConversationPlanningContext,
} from "../src/lib/bridge-planning.ts";
import { createConversationPlanningContextGetHandler, createConversationPlanningContextPostHandler } from "../src/lib/conversation-planning-context-route.ts";
import { createPlanningOverviewHandler } from "../src/lib/planning-overview-route.ts";
import { createPlanningTasksHandler } from "../src/lib/planning-tasks-route.ts";
import { createPlanningTaskHandler } from "../src/lib/planning-task-route.ts";
import { createProjectHandler, createProjectTaskHandler } from "../src/lib/project-creation-route.ts";
import {
  createProject,
  createProjectTask,
  parseConversationPlanningContext,
  parseConversationPlanningMutation,
  parsePlanningOverview,
  parsePlanningTaskPage,
  parsePlanningTaskResult,
  PublicPlanningError,
  PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS,
  readConversationPlanningContext,
  readPlanningOverview,
  readPlanningTask,
  readPlanningTasks,
  updateConversationPlanningContext,
} from "../src/lib/public-planning.ts";

const envelope = { runtime: "python" as const, schema_version: 1 as const, service: "mentat-local-bridge" as const, status: "ready" as const };
const project = { id: "project_alpha", name: "Alpha", status: "active" as const };
const task = { attention_reasons: ["overdue", "review"] as Array<"overdue" | "review">, due_date: "2026-08-29", id: "task_alpha", needs_attention: false, planned_for_today: false, planning_state: "review" as const, priority: "high" as const, project_id: project.id, project_name: project.name, review_required: true, status: "todo" as const, title: "Review Alpha", updated_at: "2026-08-30T12:00:00Z" };
const createdTask = { ...task, priority: "medium" as const };
const overview = { ...envelope, attention: [task], attention_count: 1, project_count: 1, projects: [project], today: "2026-08-30", truncated: false };
const taskPage = { ...envelope, count: 1, next_cursor: null, project, tasks: [task] };
const nonAttentionTask = { ...task, attention_reasons: [] as [], due_date: null, id: "task_plain", needs_attention: false, planning_state: "inbox" as const, priority: "medium" as const, review_required: false, title: "Plain task" };
const taskResult = { ...envelope, project, task: nonAttentionTask };
const context = { ...envelope, association: { project_id: project.id, task_id: task.id }, conversation_id: "conv_alpha", conversation_revision: 4, project, state: "ready" as const, task };
const conversation = { agent_id: "agent_alpha", archived_at: null, created_at: "2026-08-30T12:00:00Z", id: "conv_alpha", revision: 5, state: "active" as const, title: "Alpha", title_source: "manual" as const, updated_at: "2026-08-30T12:01:00Z" };
const mutation = { ...context, action: "set" as const, conversation, conversation_revision: 5 };
const clearMutation = { ...envelope, action: "clear" as const, association: null, conversation, conversation_id: "conv_alpha", conversation_revision: 5, project: null, state: "empty" as const, task: null };
const projectCreation = { ...envelope, action: "create" as const, project };
const taskCreation = { ...envelope, action: "create" as const, project, task: createdTask };
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars" };
const json = (value: unknown, status = 200) => Response.json(value, { status });
const browserHeaders = { Host: "127.0.0.1:8890", Origin: "http://127.0.0.1:8890", "Sec-Fetch-Site": "same-origin" };

test("public planning parsers accept only exact detached projections", () => {
  assert.deepEqual(parsePlanningOverview(overview), overview);
  assert.deepEqual(parsePlanningTaskPage(taskPage, project.id), taskPage);
  assert.deepEqual(parseConversationPlanningContext(context, "conv_alpha"), context);
  assert.deepEqual(parseConversationPlanningMutation(mutation, "conv_alpha"), mutation);
  const parsed = parsePlanningOverview(overview); parsed.projects[0]!.name = "Changed"; assert.equal(project.name, "Alpha");
  const hostile = [
    { ...overview, secret: "private" },
    { ...overview, project_count: 2 },
    { ...overview, attention_count: 2, truncated: false },
    { ...overview, projects: [{ ...project, path: "/private" }] },
    { ...overview, attention: [{ ...task, description: "private" }] },
    { ...overview, attention: [{ ...task, attention_reasons: ["review", "overdue"] }] },
    { ...overview, attention: [{ ...task, due_date: "2026-02-31" }] },
    { ...taskPage, project: { ...project, id: "project_other" } },
    { ...context, conversation_id: "conv_other" },
    { ...context, association: { project_id: project.id, task_id: "task_other" } },
    { ...mutation, conversation: { ...conversation, revision: 4 } },
  ];
  for (const value of hostile) assert.throws(() => value === hostile[7] ? parsePlanningTaskPage(value, project.id) : value === hostile[8] || value === hostile[9] ? parseConversationPlanningContext(value, "conv_alpha") : value === hostile[10] ? parseConversationPlanningMutation(value, "conv_alpha") : parsePlanningOverview(value), PublicPlanningError);
});

test("bridge planning reads use only fixed private paths and reject cross-target replies", async () => {
  const paths: string[] = [];
  const fetcher = async (input: string | URL | Request) => { paths.push(input.toString()); const url = new URL(input.toString()); if (url.pathname.endsWith("planning-overview")) return json(overview); if (url.pathname.endsWith("planning-tasks")) return json(taskPage); return json(context); };
  assert.deepEqual(await fetchBridgePlanningOverview(fetcher, environment), overview);
  assert.deepEqual(await fetchBridgePlanningTasks(project.id, null, fetcher, environment), taskPage);
  assert.deepEqual(await fetchBridgeConversationPlanningContext("conv_alpha", fetcher, environment), context);
  assert.deepEqual(paths, ["http://127.0.0.1:49152/bridge/v1/agent-console/planning-overview", "http://127.0.0.1:49152/bridge/v1/agent-console/planning-tasks?project_id=project_alpha", "http://127.0.0.1:49152/bridge/v1/conversations/conv_alpha/planning-context"]);
  await assert.rejects(fetchBridgePlanningTasks(project.id, null, async () => json({ ...taskPage, project: { ...project, id: "project_other" } }), environment), BridgePlanningError);
  await assert.rejects(fetchBridgeConversationPlanningContext("conv_alpha", async () => json({ ...context, conversation_id: "conv_other" }), environment), BridgePlanningError);
});

test("single planning Task read accepts a non-attention Task and binds its exact target", async () => {
  let path = "";
  const result = await fetchBridgePlanningTask(nonAttentionTask.id, async (input) => { path = input.toString(); return json(taskResult); }, environment);
  assert.deepEqual(result, taskResult);
  assert.equal(path, "http://127.0.0.1:49152/bridge/v1/agent-console/planning-task?task_id=task_plain");
  assert.deepEqual(parsePlanningTaskResult(taskResult, nonAttentionTask.id), taskResult);
  for (const hostile of [
    { ...taskResult, private_path: "/private" },
    { ...taskResult, task: { ...nonAttentionTask, id: "task_other" } },
    { ...taskResult, project: { ...project, id: "project_other" } },
    { ...taskResult, task: { ...nonAttentionTask, description: "private" } },
    { ...envelope, project },
  ]) await assert.rejects(fetchBridgePlanningTask(nonAttentionTask.id, async () => json(hostile), environment), BridgePlanningError);
});

test("bridge planning mutations bind exact bodies targets and deadline margin", async () => {
  assert.equal(PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS, 8_000);
  assert.equal(PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS - PLANNING_MUTATION_BRIDGE_TIMEOUT_MILLISECONDS, 4_000);
  const calls: Array<{ body: string; signal: AbortSignal; url: string }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => { calls.push({ body: String(init?.body), signal: init?.signal as AbortSignal, url: input.toString() }); return json(mutation); };
  assert.deepEqual(await updateBridgeConversationPlanningContext("conv_alpha", 4, project.id, task.id, fetcher, environment), mutation);
  assert.deepEqual(JSON.parse(calls[0]!.body), { expected_revision: 4, project_id: project.id, task_id: task.id });
  assert.equal(calls[0]!.url, "http://127.0.0.1:49152/bridge/v1/conversations/conv_alpha/planning-context");
  assert.equal(calls[0]!.signal.aborted, false);
  assert.deepEqual(await updateBridgeConversationPlanningContext("conv_alpha", 4, null, null, async () => json(clearMutation), environment), clearMutation);
  await assert.rejects(updateBridgeConversationPlanningContext("conv_alpha", 4, project.id, task.id, async () => json({ ...mutation, association: { project_id: project.id, task_id: "task_other" } }), environment), BridgePlanningError);
  await assert.rejects(updateBridgeConversationPlanningContext("conv_alpha", 4, project.id, task.id, async () => json({ ...mutation, conversation: { ...conversation, revision: 6 }, conversation_revision: 6 }), environment), BridgePlanningError);
});

test("bridge Project and Task creation use fixed bodies and reject private or cross-project results", async () => {
  const calls: Array<{ body: unknown; url: string }> = [];
  const projectResult = await createBridgeProject("Alpha", async (input, init) => { calls.push({ body: JSON.parse(String(init?.body)), url: input.toString() }); return json(projectCreation, 201); }, environment);
  const taskResult = await createBridgeProjectTask(project.id, "Review Alpha", null, "2026-08-29", async (input, init) => { calls.push({ body: JSON.parse(String(init?.body)), url: input.toString() }); return json(taskCreation, 201); }, environment);
  assert.deepEqual(projectResult, projectCreation); assert.deepEqual(taskResult, taskCreation);
  assert.deepEqual(calls, [{ body: { name: "Alpha" }, url: "http://127.0.0.1:49152/bridge/v1/projects" }, { body: { assigned_agent_id: null, due_date: "2026-08-29", title: "Review Alpha" }, url: "http://127.0.0.1:49152/bridge/v1/projects/project_alpha/tasks" }]);
  await assert.rejects(createBridgeProjectTask(project.id, "Review Alpha", null, null, async () => json({ ...taskCreation, task: { ...task, project_id: "project_other" } }, 201), environment), BridgePlanningError);
  await assert.rejects(createBridgeProject("Alpha", async () => json({ ...projectCreation, project: { ...project, description: "private" } }, 201), environment), BridgePlanningError);
  await assert.rejects(createBridgeProject("Beta", async () => json(projectCreation, 201), environment), BridgePlanningError);
  await assert.rejects(createBridgeProjectTask(project.id, "Different Task", null, task.due_date, async () => json(taskCreation, 201), environment), BridgePlanningError);
  await assert.rejects(createBridgeProjectTask(project.id, task.title, null, null, async () => json(taskCreation, 201), environment), BridgePlanningError);
});

test("planning GET routes accept exact same-origin reads and reject query widening", async () => {
  const overviewHandler = createPlanningOverviewHandler({ fetchOverview: async () => overview, gatewayPort: "8890" });
  const tasksHandler = createPlanningTasksHandler({ fetchTasks: async () => taskPage, gatewayPort: "8890" });
  const contextHandler = createConversationPlanningContextGetHandler({ gatewayPort: "8890", readContext: async () => context });
  assert.equal((await overviewHandler(new Request("http://127.0.0.1:8890/api/agent-console/planning-overview", { headers: browserHeaders }))).status, 200);
  assert.equal((await tasksHandler(new Request("http://127.0.0.1:8890/api/agent-console/planning-tasks?project_id=project_alpha", { headers: browserHeaders }))).status, 200);
  assert.equal((await contextHandler(new Request("http://127.0.0.1:8890/api/conversations/conv_alpha/planning-context", { headers: browserHeaders }), { params: Promise.resolve({ conversationId: "conv_alpha" }) })).status, 200);
  assert.equal((await overviewHandler(new Request("http://127.0.0.1:8890/api/agent-console/planning-overview?extra=1", { headers: browserHeaders }))).status, 400);
  assert.equal((await tasksHandler(new Request("http://127.0.0.1:8890/api/agent-console/planning-tasks?project_id=project_alpha&project_id=project_alpha", { headers: browserHeaders }))).status, 400);
  assert.equal((await tasksHandler(new Request("http://127.0.0.1:8890/api/agent-console/planning-tasks?project_id=project_alpha&q=x", { headers: browserHeaders }))).status, 400);
  assert.equal((await contextHandler(new Request("http://127.0.0.1:8890/api/conversations/conv_alpha/planning-context?x=1", { headers: browserHeaders }), { params: Promise.resolve({ conversationId: "conv_alpha" }) })).status, 400);
});

test("single planning Task route requires exactly one canonical task_id query", async () => {
  const handler = createPlanningTaskHandler({ fetchTask: async () => taskResult, gatewayPort: "8890" });
  const request = (query: string) => new Request(`http://127.0.0.1:8890/api/agent-console/planning-task${query}`, { headers: browserHeaders });
  assert.equal((await handler(request("?task_id=task_plain"))).status, 200);
  for (const query of ["", "?task_id=", "?task_id=task_plain&task_id=task_plain", "?task_id=task_plain&cursor=x", "?id=task_plain", "?task_id=../private"]) assert.equal((await handler(request(query))).status, 400);
});

test("planning POST routes require exact same-origin bounded bodies", async () => {
  const contextHandler = createConversationPlanningContextPostHandler({ gatewayPort: "8890", updateContext: async () => mutation });
  const projectHandler = createProjectHandler({ create: async () => projectCreation, gatewayPort: "8890" });
  const taskHandler = createProjectTaskHandler({ create: async () => taskCreation, gatewayPort: "8890" });
  const post = (url: string, body: unknown, headers = browserHeaders) => new Request(url, { body: JSON.stringify(body), headers: { ...headers, "Content-Type": "application/json" }, method: "POST" });
  assert.equal((await contextHandler(post("http://127.0.0.1:8890/api/conversations/conv_alpha/planning-context", { expected_revision: 4, project_id: project.id, task_id: task.id }), { params: Promise.resolve({ conversationId: "conv_alpha" }) })).status, 200);
  assert.equal((await projectHandler(post("http://127.0.0.1:8890/api/projects", { name: "Alpha" }))).status, 201);
  assert.equal((await taskHandler(post("http://127.0.0.1:8890/api/projects/project_alpha/tasks", { assigned_agent_id: null, due_date: null, title: "Task" }), { params: Promise.resolve({ projectId: project.id }) })).status, 201);
  const invalidBodies = [{ expected_revision: 4, project_id: null, task_id: task.id }, { expected_revision: 4, project_id: project.id, task_id: null, extra: true }, { expected_revision: 0, project_id: null, task_id: null }];
  for (const body of invalidBodies) assert.equal((await contextHandler(post("http://127.0.0.1:8890/api/conversations/conv_alpha/planning-context", body), { params: Promise.resolve({ conversationId: "conv_alpha" }) })).status, 400);
  assert.equal((await projectHandler(post("http://127.0.0.1:8890/api/projects", { name: " Alpha" }))).status, 400);
  assert.equal((await taskHandler(post("http://127.0.0.1:8890/api/projects/project_alpha/tasks", { assigned_agent_id: null, due_date: "not-date", title: "Task" }), { params: Promise.resolve({ projectId: project.id }) })).status, 400);
  assert.equal((await taskHandler(post("http://127.0.0.1:8890/api/projects/project_alpha/tasks", { assigned_agent_id: null, due_date: "2026-02-31", title: "Task" }), { params: Promise.resolve({ projectId: project.id }) })).status, 400);
  assert.equal((await projectHandler(post("http://127.0.0.1:8890/api/projects", { name: "Alpha" }, { Host: "127.0.0.1:8890", Origin: "http://evil.test", "Sec-Fetch-Site": "cross-site" }))).status, 403);
});

test("public planning clients build exact requests and never return envelope or private fields", async () => {
  const original = globalThis.fetch; const calls: Array<{ body: string | undefined; method: string; path: string }> = [];
  globalThis.fetch = async (input, init) => { const url = new URL(input.toString(), "http://127.0.0.1:8890"); calls.push({ body: init?.body?.toString(), method: init?.method ?? "GET", path: `${url.pathname}${url.search}` }); if (url.pathname.endsWith("planning-overview")) return json(overview); if (url.pathname.endsWith("planning-tasks")) return json(taskPage); if (url.pathname.endsWith("planning-task")) return json(taskResult); if (url.pathname === "/api/projects") return json(projectCreation, 201); if (url.pathname.endsWith("/tasks")) return json(taskCreation, 201); if (init?.method === "POST") return json(mutation); return json(context); };
  try {
    assert.deepEqual(await readPlanningOverview(), overview); assert.deepEqual(await readPlanningTasks(project.id, null), taskPage); assert.deepEqual(await readPlanningTask(nonAttentionTask.id), taskResult); assert.deepEqual(await readConversationPlanningContext("conv_alpha"), context); assert.deepEqual(await updateConversationPlanningContext("conv_alpha", 4, project.id, task.id), mutation); assert.deepEqual(await createProject("Alpha"), project); assert.deepEqual(await createProjectTask(project.id, "Review Alpha", null, task.due_date), createdTask);
    assert.deepEqual(calls.map((call) => call.path), ["/api/agent-console/planning-overview", "/api/agent-console/planning-tasks?project_id=project_alpha", "/api/agent-console/planning-task?task_id=task_plain", "/api/conversations/conv_alpha/planning-context", "/api/conversations/conv_alpha/planning-context", "/api/projects", "/api/projects/project_alpha/tasks"]);
    assert.deepEqual(JSON.parse(calls[4]!.body ?? "{}"), { expected_revision: 4, project_id: project.id, task_id: task.id });
    assert.deepEqual(JSON.parse(calls[6]!.body ?? "{}"), { assigned_agent_id: null, due_date: task.due_date, title: "Review Alpha" });
  } finally { globalThis.fetch = original; }
});

test("planning clients map only fixed errors and bound declared or streamed bytes", async () => {
  await assert.rejects(fetchBridgePlanningOverview(async () => json({ ...envelope, status: "unavailable" }, 503), environment), (error: unknown) => error instanceof BridgePlanningError && error.code === "bridge_unavailable");
  await assert.rejects(fetchBridgePlanningOverview(async () => new Response("{}", { headers: { "Content-Length": "9999999", "Content-Type": "application/json" } }), environment), BridgePlanningError);
  const original = globalThis.fetch; globalThis.fetch = async () => json({ schema_version: 1, status: "conflict" }, 409);
  try { await assert.rejects(updateConversationPlanningContext("conv_alpha", 4, null, null), (error: unknown) => error instanceof PublicPlanningError && error.code === "conflict"); } finally { globalThis.fetch = original; }
  await assert.rejects(createProjectTask(project.id, "Task", null, "2026-02-31"), (error: unknown) => error instanceof PublicPlanningError && error.code === "invalid");
});

test("planning routes map only fixed bridge failures without leaking details", async () => {
  const cases: Array<[BridgePlanningError, number, string]> = [
    [new BridgePlanningError("planning_request_invalid"), 400, "invalid"],
    [new BridgePlanningError("planning_not_found"), 404, "not_found"],
    [new BridgePlanningError("planning_conflict"), 409, "conflict"],
    [new BridgePlanningError("planning_active_run"), 409, "active_run"],
    [new BridgePlanningError("planning_queue_active"), 409, "queue_active"],
    [new BridgePlanningError("bridge_unsupported"), 501, "unsupported"],
    [new BridgePlanningError("bridge_unavailable"), 503, "unavailable"],
    [new BridgePlanningError("private-canary"), 502, "error"],
  ];
  for (const [error, status, state] of cases) {
    const handler = createPlanningOverviewHandler({ fetchOverview: async () => { throw error; }, gatewayPort: "8890" });
    const response = await handler(new Request("http://127.0.0.1:8890/api/agent-console/planning-overview", { headers: browserHeaders }));
    assert.equal(response.status, status); assert.deepEqual(await response.json(), { schema_version: 1, status: state });
  }
});
