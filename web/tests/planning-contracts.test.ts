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
  fetchBridgePlanningTaskDependencies,
  fetchBridgePlanningDependencyMap,
  fetchBridgePlanningDependencyPicker,
  fetchBridgePlanningTaskExecution,
  fetchBridgePlanningTaskDelegation,
  previewBridgePlanningTaskRunOnce,
  confirmBridgePlanningTaskRunOnce,
  reviewBridgePlanningTaskExecution,
  fetchBridgePlanningTasks,
  moveBridgePlanningTask,
  updateBridgePlanningProject,
  updateBridgePlanningTask,
  updateBridgeConversationPlanningContext,
} from "../src/lib/bridge-planning.ts";
import { createConversationPlanningContextGetHandler, createConversationPlanningContextPostHandler } from "../src/lib/conversation-planning-context-route.ts";
import { createPlanningOverviewHandler } from "../src/lib/planning-overview-route.ts";
import { createPlanningTasksHandler } from "../src/lib/planning-tasks-route.ts";
import { createPlanningTaskHandler } from "../src/lib/planning-task-route.ts";
import { createPlanningTaskDependenciesHandler } from "../src/lib/planning-task-dependencies-route.ts";
import { createPlanningDependencyMapHandler } from "../src/lib/planning-dependency-map-route.ts";
import { createPlanningDependencyPickerHandler } from "../src/lib/planning-dependency-picker-route.ts";
import { createPlanningMutationHandler } from "../src/lib/planning-mutation-route.ts";
import { createPlanningTaskExecutionGetHandler, createPlanningTaskRunOncePreviewHandler, createPlanningTaskRunOnceConfirmHandler, createPlanningTaskExecutionReviewHandler } from "../src/lib/planning-task-execution-route.ts";
import { createPlanningTaskDelegationGetHandler } from "../src/lib/planning-task-delegation-route.ts";
import { createProjectHandler, createProjectTaskHandler } from "../src/lib/project-creation-route.ts";
import {
  createProject,
  createProjectTask,
  parseConversationPlanningContext,
  parseConversationPlanningMutation,
  parsePlanningOverview,
  parsePlanningTaskPage,
  parsePlanningTaskDetailResult,
  parsePlanningTaskDependencies,
  parsePlanningDependencyMap,
  parsePlanningDependencyPickerPage,
  parsePlanningTaskResult,
  PublicPlanningError,
  PLANNING_MUTATION_PUBLIC_TIMEOUT_MILLISECONDS,
  readConversationPlanningContext,
  readPlanningOverview,
  readPlanningTask,
  readPlanningTaskDependencies,
  readPlanningDependencyMap,
  readPlanningDependencyPicker,
  readPlanningTasks,
  updateConversationPlanningContext,
} from "../src/lib/public-planning.ts";
import {
  confirmPlanningTaskRunOnce,
  parsePlanningRunOncePreview,
  parsePlanningTaskExecution,
  parsePlanningTaskExecutionMutation,
  previewPlanningTaskRunOnce,
  readPlanningTaskExecution,
  reviewPlanningTaskExecution,
} from "../src/lib/public-planning-task-execution.ts";
import { parsePlanningTaskDelegation, readPlanningTaskDelegation } from "../src/lib/public-planning-task-delegation.ts";

const envelope = { runtime: "python" as const, schema_version: 1 as const, service: "mentat-local-bridge" as const, status: "ready" as const };
const project = { id: "project_alpha", name: "Alpha", revision: 1, status: "active" as const };
const task = { attention_reasons: ["overdue", "review"] as Array<"overdue" | "review">, blocked: false, deferred: false, due_date: "2026-08-29", id: "task_alpha", needs_attention: false, planned_for_today: false, planning_state: "review" as const, priority: "high" as const, project_id: project.id, project_name: project.name, review_required: true, revision: 1, status: "todo" as const, title: "Review Alpha", updated_at: "2026-08-30T12:00:00Z", workflow_stage: "review" as const };
const listTask = { ...task, description_preview: "Prepare the Alpha review." };
const createdTask = { ...task, priority: "medium" as const };
const overview = { ...envelope, attention: [task], attention_count: 1, project_count: 1, projects: [project], today: "2026-08-30", truncated: false };
const taskPage = { ...envelope, count: 1, next_cursor: null, project, tasks: [listTask] };
const nonAttentionTask = { ...task, attention_reasons: [] as [], due_date: null, id: "task_plain", needs_attention: false, planning_state: "inbox" as const, priority: "medium" as const, review_required: false, title: "Plain task" };
const taskResult = { ...envelope, project, task: nonAttentionTask };
const taskDetailResult = { ...envelope, project, task: { ...nonAttentionTask, assigned_agent_id: null, description: "A bounded description.", estimated_minutes: 30, recurrence: null, subtasks: [], tags: [] } };
const executionTask = { ...nonAttentionTask, assigned_agent_id: "agent_alpha", workflow_stage: "planned" as const };
const taskExecution = { ...envelope, execution: { attempt_count: 0, attempts: [], available: true, reason: null, review: { available: false, run_id: null } }, task: executionTask };
const taskDelegation = { ...envelope, delegation: { attempts: 2, available: true as const, last_outcome: "completed" as const, last_synced_at: "2026-08-30T11:59:00Z", latest_question: "Confirm the deployment window.", review_state: "pending" as const, state: "ready_for_review" as const, summary: "The delegated implementation is ready for review.", sync_state: "synced" as const, updated_at: "2026-08-30T12:00:00Z" }, task_id: nonAttentionTask.id };
const notDelegated = { ...envelope, delegation: { available: false as const, reason: "not_delegated" as const }, task_id: nonAttentionTask.id };
const runOncePreview = { ...envelope, action: "run_once" as const, confirmation_id: "a".repeat(64), requires_confirmation: true as const, task: executionTask };
const executionAttempt = { agent_id: "agent_alpha", completed_at: null, completion_reason: null, created_at: "2026-08-30T12:00:00Z", dispatch_state: "accepted", partial: false, review_action: null, review_note: null, review_task_revision: null, run_id: "run_alpha", runtime_type: "codex", state: "dispatched" as const, status: "running", task_revision: 1, terminal_finalized: false, updated_at: "2026-08-30T12:00:00Z" };
const runOnceMutation = { ...envelope, action: "run_once" as const, duplicate: false, execution: { attempt_count: 1, attempts: [executionAttempt], available: false, reason: "unavailable" as const, review: { available: false, run_id: null } }, task: { ...executionTask, workflow_stage: "in_progress" as const } };
const acceptMutation = { ...runOnceMutation, action: "accept" as const, execution: { ...runOnceMutation.execution, review: { available: false, run_id: null } }, task: { ...executionTask, revision: 2, workflow_stage: "done" as const } };
const dependencyReference = { blocked: false, id: "task_dependency", project_id: "project_beta", project_name: "Beta", title: "Prepare Beta", workflow_stage: "planned" as const };
const dependencies = { ...envelope, dependent_count: 0, dependents: [], dependents_truncated: false, prerequisite_count: 1, prerequisites: [dependencyReference], prerequisites_truncated: false, task_id: nonAttentionTask.id, task_revision: 1 };
const picker = { ...envelope, candidate_count: 1, candidates: [dependencyReference], match_count: 1, next_cursor: null, query: "Beta", task_id: nonAttentionTask.id, truncated: false };
const dependencyMap = { ...envelope, edge_count: 2, edge_total: 2, edges: [{ from_task_id: nonAttentionTask.id, to_task_id: dependencyReference.id }, { from_task_id: "task_dependent", to_task_id: nonAttentionTask.id }], edges_truncated: false, external_stub_count: 1, external_stub_total: 1, external_stubs: [dependencyReference], external_stubs_truncated: false, node_count: 2, node_total: 2, nodes: [
  { blocked: false, id: nonAttentionTask.id, project_id: project.id, project_name: project.name, title: nonAttentionTask.title, workflow_stage: nonAttentionTask.workflow_stage },
  { blocked: false, id: "task_dependent", project_id: project.id, project_name: project.name, title: "Dependent", workflow_stage: "planned" as const },
], nodes_truncated: false, project };
const context = { ...envelope, association: { project_id: project.id, task_id: task.id }, conversation_id: "conv_alpha", conversation_revision: 4, project, state: "ready" as const, task };
const conversation = { agent_id: "agent_alpha", archived_at: null, created_at: "2026-08-30T12:00:00Z", id: "conv_alpha", revision: 5, state: "active" as const, title: "Alpha", title_source: "manual" as const, updated_at: "2026-08-30T12:01:00Z" };
const mutation = { ...context, action: "set" as const, conversation, conversation_revision: 5 };
const clearMutation = { ...envelope, action: "clear" as const, association: null, conversation, conversation_id: "conv_alpha", conversation_revision: 5, project: null, state: "empty" as const, task: null };
const projectCreation = { ...envelope, action: "create" as const, project };
const taskCreation = { ...envelope, action: "create" as const, project, task: createdTask };
const projectMutation = { ...envelope, action: "rename" as const, project: { ...project, name: "Renamed", revision: 2 } };
const taskMutation = { ...envelope, action: "edit" as const, project, task: { ...task, revision: 2, workflow_stage: "in_progress" as const, planning_state: "in_progress" as const, status: "in progress" as const } };
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
    { ...overview, runtime_reference: "private" },
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

test("dependency reads use fixed targets and reject widened or cross-task projections", async () => {
  let dependencyPath = ""; let pickerPath = "";
  assert.deepEqual(await fetchBridgePlanningTaskDependencies(nonAttentionTask.id, async (input) => { dependencyPath = input.toString(); return json(dependencies); }, environment), dependencies);
  assert.deepEqual(await fetchBridgePlanningDependencyPicker(nonAttentionTask.id, "Beta", null, async (input) => { pickerPath = input.toString(); return json(picker); }, environment), picker);
  assert.equal(dependencyPath, "http://127.0.0.1:49152/bridge/v1/agent-console/planning-task-dependencies?task_id=task_plain");
  assert.equal(pickerPath, "http://127.0.0.1:49152/bridge/v1/agent-console/planning-dependency-picker?task_id=task_plain&q=Beta");
  assert.deepEqual(parsePlanningTaskDependencies(dependencies, nonAttentionTask.id), dependencies);
  assert.deepEqual(parsePlanningDependencyPickerPage(picker, nonAttentionTask.id, "Beta"), picker);
  await assert.rejects(fetchBridgePlanningTaskDependencies(nonAttentionTask.id, async () => json({ ...dependencies, task_id: "task_other" }), environment), BridgePlanningError);
  await assert.rejects(fetchBridgePlanningDependencyPicker(nonAttentionTask.id, "Beta", null, async () => json({ ...picker, candidates: [{ ...dependencyReference, private_path: "x" }] }), environment), BridgePlanningError);
});

test("dependency-map reads use one fixed selected-Project target and reject widened topology", async () => {
  let mapPath = "";
  assert.deepEqual(await fetchBridgePlanningDependencyMap(project.id, "", "all", async (input) => { mapPath = input.toString(); return json(dependencyMap); }, environment), dependencyMap);
  assert.equal(mapPath, "http://127.0.0.1:49152/bridge/v1/agent-console/planning-dependency-map?project_id=project_alpha");
  assert.deepEqual(parsePlanningDependencyMap(dependencyMap, project.id), dependencyMap);
  for (const hostile of [
    { ...dependencyMap, project: { ...project, id: "project_other" } },
    { ...dependencyMap, nodes: [{ ...dependencyMap.nodes[0], description: "private" }, dependencyMap.nodes[1]] },
    { ...dependencyMap, external_stubs: [{ ...dependencyReference, project_id: project.id, project_name: project.name }] },
    { ...dependencyMap, edges: [{ from_task_id: "task_private", to_task_id: nonAttentionTask.id }] },
    { ...dependencyMap, edge_count: 3 },
  ]) await assert.rejects(fetchBridgePlanningDependencyMap(project.id, "", "all", async () => json(hostile), environment), BridgePlanningError);
});

test("dependency-map reads bind one bounded filter and saved view to the fixed Project route", async () => {
  let path = "";
  assert.deepEqual(await fetchBridgePlanningDependencyMap(project.id, "Alpha", "review", async (input) => { path = input.toString(); return json(dependencyMap); }, environment), dependencyMap);
  assert.equal(path, "http://127.0.0.1:49152/bridge/v1/agent-console/planning-dependency-map?project_id=project_alpha&q=Alpha&view=review");
  await assert.rejects(fetchBridgePlanningDependencyMap(project.id, " Alpha", "all", async () => json(dependencyMap), environment), BridgePlanningError);
  await assert.rejects(fetchBridgePlanningDependencyMap(project.id, "Alpha", "not-a-view" as "all", async () => json(dependencyMap), environment), BridgePlanningError);
});

test("selected Task details accept editable bounded fields without widening list projections", () => {
  assert.deepEqual(parsePlanningTaskDetailResult(taskDetailResult, nonAttentionTask.id), taskDetailResult);
  assert.throws(() => parsePlanningTaskDetailResult({ ...taskDetailResult, task: { ...taskDetailResult.task, runtime_reference: "private" } }, nonAttentionTask.id), PublicPlanningError);
});

test("detailed planning mutations use named exact routes and bodies", async () => {
  const calls: Array<{ body: unknown; url: string }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ body: JSON.parse(String(init?.body)), url: input.toString() });
    return json(input.toString().endsWith("/edit") ? taskMutation : projectMutation);
  };
  assert.deepEqual(await updateBridgePlanningProject(project.id, 1, "rename", "Renamed", fetcher, environment), projectMutation);
  assert.deepEqual(await updateBridgePlanningTask(task.id, 1, { workflow_stage: "in_progress" }, fetcher, environment), taskMutation);
  assert.deepEqual(await moveBridgePlanningTask(task.id, 2, project.id, 1, async (input, init) => { calls.push({ body: JSON.parse(String(init?.body)), url: input.toString() }); return json({ ...taskMutation, action: "move" as const }); }, environment), { ...taskMutation, action: "move" as const });
  assert.deepEqual(calls, [
    { body: { action: "rename", expected_revision: 1, name: "Renamed" }, url: "http://127.0.0.1:49152/bridge/v1/planning/projects/project_alpha" },
    { body: { changes: { workflow_stage: "in_progress" }, expected_revision: 1 }, url: "http://127.0.0.1:49152/bridge/v1/planning/tasks/task_alpha/edit" },
    { body: { expected_project_revision: 1, expected_task_revision: 2, project_id: project.id }, url: "http://127.0.0.1:49152/bridge/v1/planning/tasks/task_alpha/move" },
  ]);
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

test("dependency read routes require exact canonical queries", async () => {
  const dependenciesHandler = createPlanningTaskDependenciesHandler({ fetchDependencies: async () => dependencies, gatewayPort: "8890" });
  const pickerHandler = createPlanningDependencyPickerHandler({ fetchPicker: async () => picker, gatewayPort: "8890" });
  const dependencyRequest = (query: string) => new Request(`http://127.0.0.1:8890/api/agent-console/planning-task-dependencies${query}`, { headers: browserHeaders });
  const pickerRequest = (query: string) => new Request(`http://127.0.0.1:8890/api/agent-console/planning-dependency-picker${query}`, { headers: browserHeaders });
  assert.equal((await dependenciesHandler(dependencyRequest(`?task_id=${nonAttentionTask.id}`))).status, 200);
  assert.equal((await dependenciesHandler(dependencyRequest(`?task_id=${nonAttentionTask.id}&task_id=${nonAttentionTask.id}`))).status, 400);
  assert.equal((await pickerHandler(pickerRequest(`?task_id=${nonAttentionTask.id}&q=Beta`))).status, 200);
  assert.equal((await pickerHandler(pickerRequest(`?task_id=${nonAttentionTask.id}&cursor=not%20opaque`))).status, 400);
  assert.equal((await pickerHandler(pickerRequest(`?task_id=${nonAttentionTask.id}&extra=x`))).status, 400);
});

test("dependency-map route requires exactly one canonical project_id query", async () => {
  const received: Array<[string, string, string]> = [];
  const handler = createPlanningDependencyMapHandler({ fetchDependencyMap: async (projectId, query, savedView) => { received.push([projectId, query, savedView]); return dependencyMap; }, gatewayPort: "8890" });
  const request = (query: string) => new Request(`http://127.0.0.1:8890/api/agent-console/planning-dependency-map${query}`, { headers: browserHeaders });
  assert.equal((await handler(request(`?project_id=${project.id}`))).status, 200);
  assert.equal((await handler(request(`?project_id=${project.id}&q=Alpha&view=review`))).status, 200);
  assert.deepEqual(received, [[project.id, "", "all"], [project.id, "Alpha", "review"]]);
  for (const query of ["", "?project_id=", `?project_id=${project.id}&project_id=${project.id}`, `?project_id=${project.id}&task_id=${task.id}`, `?project_id=${project.id}&q=`, `?project_id=${project.id}&q=%20Alpha`, `?project_id=${project.id}&view=all`, `?project_id=${project.id}&view=blocked`, "?project_id=../private"]) assert.equal((await handler(request(query))).status, 400);
  assert.equal((await handler(new Request(`http://127.0.0.1:8890/api/agent-console/planning-dependency-map?project_id=${project.id}`, { headers: { Host: "127.0.0.1:8890", Origin: "http://evil.test", "Sec-Fetch-Site": "cross-site" } }))).status, 403);
});

test("detailed planning mutation route keeps the gateway same-origin, bounded, and named", async () => {
  const calls: unknown[] = [];
  const handler = createPlanningMutationHandler({
    gatewayPort: "8890",
    updateProject: async (...args) => { calls.push(args); return projectMutation; },
    updateTask: async (...args) => { calls.push(args); return taskMutation; },
    moveTask: async (...args) => { calls.push(args); return { ...taskMutation, action: "move" as const }; },
  });
  const post = (url: string, value: unknown, headers = browserHeaders) => new Request(url, { body: JSON.stringify(value), headers: { ...headers, "Content-Type": "application/json" }, method: "POST" });
  assert.equal((await handler(post(`http://127.0.0.1:8890/api/planning/projects/${project.id}/rename`, { action: "rename", expected_revision: 1, name: "Renamed" }), { params: Promise.resolve({ action: "rename", id: project.id, kind: "projects" }) })).status, 200);
  assert.equal((await handler(post(`http://127.0.0.1:8890/api/planning/tasks/${task.id}/edit`, { changes: { workflow_stage: "in_progress" }, expected_revision: 1 }), { params: Promise.resolve({ action: "edit", id: task.id, kind: "tasks" }) })).status, 200);
  assert.equal((await handler(post(`http://127.0.0.1:8890/api/planning/tasks/${task.id}/move`, { expected_project_revision: 1, expected_task_revision: 2, project_id: project.id }), { params: Promise.resolve({ action: "move", id: task.id, kind: "tasks" }) })).status, 200);
  assert.deepEqual(calls, [[project.id, 1, "rename", "Renamed"], [task.id, 1, { workflow_stage: "in_progress" }], [task.id, 2, project.id, 1]]);
  assert.equal((await handler(post(`http://127.0.0.1:8890/api/planning/tasks/${task.id}/edit`, { changes: { unknown: true }, expected_revision: 1 }), { params: Promise.resolve({ action: "edit", id: task.id, kind: "tasks" }) })).status, 400);
  assert.equal((await handler(post(`http://127.0.0.1:8890/api/planning/tasks/${task.id}/edit`, { changes: {}, expected_revision: 1 }), { params: Promise.resolve({ action: "edit", id: task.id, kind: "tasks" }) })).status, 400);
  assert.equal((await handler(post(`http://127.0.0.1:8890/api/planning/tasks/${task.id}/edit`, { changes: {}, expected_revision: 1 }, { Host: "127.0.0.1:8890", Origin: "http://evil.test", "Sec-Fetch-Site": "cross-site" }), { params: Promise.resolve({ action: "edit", id: task.id, kind: "tasks" }) })).status, 403);
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

test("public dependency clients use only named same-origin routes", async () => {
  const original = globalThis.fetch; const paths: string[] = [];
  globalThis.fetch = async (input) => { const url = new URL(input.toString(), "http://127.0.0.1:8890"); paths.push(`${url.pathname}${url.search}`); return url.pathname.endsWith("planning-task-dependencies") ? json(dependencies) : json(picker); };
  try {
    assert.deepEqual(await readPlanningTaskDependencies(nonAttentionTask.id), dependencies);
    assert.deepEqual(await readPlanningDependencyPicker(nonAttentionTask.id, "Beta"), picker);
    assert.deepEqual(paths, ["/api/agent-console/planning-task-dependencies?task_id=task_plain", "/api/agent-console/planning-dependency-picker?task_id=task_plain&q=Beta"]);
  } finally { globalThis.fetch = original; }
});

test("public dependency-map client uses only its named same-origin route", async () => {
  const original = globalThis.fetch; const paths: string[] = [];
  globalThis.fetch = async (input) => { const url = new URL(input.toString(), "http://127.0.0.1:8890"); paths.push(`${url.pathname}${url.search}`); return json(dependencyMap); };
  try {
    assert.deepEqual(await readPlanningDependencyMap(project.id), dependencyMap);
    assert.deepEqual(await readPlanningDependencyMap(project.id, "Alpha", "review"), dependencyMap);
    assert.deepEqual(paths, ["/api/agent-console/planning-dependency-map?project_id=project_alpha", "/api/agent-console/planning-dependency-map?project_id=project_alpha&q=Alpha&view=review"]);
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

test("Task execution uses fixed bounded projections and exact run-once and review bodies", async () => {
  assert.deepEqual(parsePlanningTaskExecution(taskExecution, nonAttentionTask.id), taskExecution);
  assert.deepEqual(parsePlanningRunOncePreview(runOncePreview, nonAttentionTask.id, 1), runOncePreview);
  assert.deepEqual(parsePlanningTaskExecutionMutation(runOnceMutation, nonAttentionTask.id), runOnceMutation);
  assert.throws(() => parsePlanningTaskExecution({ ...taskExecution, execution: { ...taskExecution.execution, attempts: [{ ...runOnceMutation.execution.attempts[0], private_reference: "no" }] } }, nonAttentionTask.id), PublicPlanningError);
  const calls: Array<{ body: unknown; url: string }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ body: init?.body ? JSON.parse(String(init.body)) : null, url: input.toString() });
    const url = input.toString();
    if (url.endsWith("/preview")) return json(runOncePreview);
    if (url.endsWith("/run-once")) return json(runOnceMutation, 202);
    if (url.endsWith("/review")) return json(acceptMutation);
    if (url.includes("planning-task-execution")) return json(taskExecution);
    return json(taskExecution);
  };
  assert.deepEqual(await fetchBridgePlanningTaskExecution(nonAttentionTask.id, fetcher, environment), taskExecution);
  assert.deepEqual(await previewBridgePlanningTaskRunOnce(nonAttentionTask.id, 1, fetcher, environment), runOncePreview);
  assert.deepEqual(await confirmBridgePlanningTaskRunOnce(nonAttentionTask.id, 1, "key_alpha_123456", runOncePreview.confirmation_id, fetcher, environment), runOnceMutation);
  assert.deepEqual(await confirmBridgePlanningTaskRunOnce(nonAttentionTask.id, 1, "key_replay_12345", runOncePreview.confirmation_id, async () => json(runOnceMutation, 200), environment), runOnceMutation);
  assert.deepEqual(await reviewBridgePlanningTaskExecution(nonAttentionTask.id, 1, "accept", null, "key_beta_1234567", fetcher, environment), acceptMutation);
  assert.deepEqual(calls, [
    { body: null, url: "http://127.0.0.1:49152/bridge/v1/agent-console/planning-task-execution?task_id=task_plain" },
    { body: { expected_revision: 1, task_id: nonAttentionTask.id }, url: "http://127.0.0.1:49152/bridge/v1/agent-console/planning-task-execution/run-once/preview" },
    { body: { confirmation_id: runOncePreview.confirmation_id, expected_revision: 1, idempotency_key: "key_alpha_123456", task_id: nonAttentionTask.id }, url: "http://127.0.0.1:49152/bridge/v1/agent-console/planning-task-execution/run-once" },
    { body: { action: "accept", expected_revision: 1, idempotency_key: "key_beta_1234567", task_id: nonAttentionTask.id }, url: "http://127.0.0.1:49152/bridge/v1/agent-console/planning-task-execution/review" },
  ]);
});

test("Task delegation uses only the selected Task's fixed safe summary", async () => {
  assert.deepEqual(parsePlanningTaskDelegation(taskDelegation, nonAttentionTask.id), taskDelegation);
  assert.deepEqual(parsePlanningTaskDelegation(notDelegated, nonAttentionTask.id), notDelegated);
  assert.throws(() => parsePlanningTaskDelegation({ ...taskDelegation, delegation: { ...taskDelegation.delegation, private_reference: "no" } }, nonAttentionTask.id), PublicPlanningError);
  assert.throws(() => parsePlanningTaskDelegation({ ...taskDelegation, task_id: "task_other" }, nonAttentionTask.id), PublicPlanningError);
  const calls: string[] = [];
  const fetcher = async (input: string | URL | Request) => { calls.push(input.toString()); return json(taskDelegation); };
  assert.deepEqual(await fetchBridgePlanningTaskDelegation(nonAttentionTask.id, fetcher, environment), taskDelegation);
  assert.deepEqual(calls, ["http://127.0.0.1:49152/bridge/v1/agent-console/planning-task-delegation?task_id=task_plain"]);
  const get = createPlanningTaskDelegationGetHandler({ gatewayPort: "8890", readDelegation: async () => taskDelegation });
  assert.equal((await get(new Request(`http://127.0.0.1:8890/api/agent-console/planning-task-delegation?task_id=${nonAttentionTask.id}`, { headers: browserHeaders }))).status, 200);
  assert.equal((await get(new Request(`http://127.0.0.1:8890/api/agent-console/planning-task-delegation?task_id=${nonAttentionTask.id}&extra=1`, { headers: browserHeaders }))).status, 400);
  const original = globalThis.fetch;
  const publicCalls: string[] = [];
  globalThis.fetch = async (input) => { publicCalls.push(input.toString()); return json(notDelegated); };
  try {
    assert.deepEqual(await readPlanningTaskDelegation(nonAttentionTask.id), notDelegated);
    assert.deepEqual(publicCalls, ["/api/agent-console/planning-task-delegation?task_id=task_plain"]);
  } finally { globalThis.fetch = original; }
});

test("Task execution routes keep all browser input exact and same-origin", async () => {
  const get = createPlanningTaskExecutionGetHandler({ gatewayPort: "8890", readExecution: async () => taskExecution });
  const preview = createPlanningTaskRunOncePreviewHandler({ gatewayPort: "8890", preview: async () => runOncePreview });
  const confirm = createPlanningTaskRunOnceConfirmHandler({ gatewayPort: "8890", confirm: async () => runOnceMutation });
  const review = createPlanningTaskExecutionReviewHandler({ gatewayPort: "8890", review: async () => acceptMutation });
  const params = { params: Promise.resolve({ taskId: nonAttentionTask.id }) };
  const post = (url: string, value: unknown) => new Request(url, { body: JSON.stringify(value), headers: { ...browserHeaders, "Content-Type": "application/json" }, method: "POST" });
  assert.equal((await get(new Request(`http://127.0.0.1:8890/api/agent-console/planning-task-execution?task_id=${nonAttentionTask.id}`, { headers: browserHeaders }))).status, 200);
  assert.equal((await preview(post(`http://127.0.0.1:8890/api/planning/tasks/${nonAttentionTask.id}/execution/run-once/preview`, { expected_revision: 1 }), params)).status, 200);
  assert.equal((await confirm(post(`http://127.0.0.1:8890/api/planning/tasks/${nonAttentionTask.id}/execution/run-once`, { confirmation_id: runOncePreview.confirmation_id, expected_revision: 1, idempotency_key: "key_alpha_123456" }), params)).status, 202);
  assert.equal((await review(post(`http://127.0.0.1:8890/api/planning/tasks/${nonAttentionTask.id}/execution/review`, { action: "request_changes", expected_revision: 1, idempotency_key: "key_beta_1234567", note: "Please revise the summary." }), params)).status, 200);
  assert.equal((await preview(post(`http://127.0.0.1:8890/api/planning/tasks/${nonAttentionTask.id}/execution/run-once/preview`, { expected_revision: 1, extra: true }), params)).status, 400);
  assert.equal((await review(post(`http://127.0.0.1:8890/api/planning/tasks/${nonAttentionTask.id}/execution/review`, { action: "accept", expected_revision: 1, idempotency_key: "key_beta_1234567", note: "not allowed" }), params)).status, 400);
  assert.equal((await confirm(post(`http://127.0.0.1:8890/api/planning/tasks/${nonAttentionTask.id}/execution/run-once`, { confirmation_id: runOncePreview.confirmation_id, expected_revision: 1, idempotency_key: "short_key" }), params)).status, 400);
  assert.equal((await get(new Request(`http://127.0.0.1:8890/api/agent-console/planning-task-execution?task_id=${nonAttentionTask.id}&extra=1`, { headers: browserHeaders }))).status, 400);
});

test("public Task execution clients use only named same-origin routes", async () => {
  const original = globalThis.fetch; const calls: Array<{ body: unknown; method: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), "http://127.0.0.1:8890"); calls.push({ body: init?.body ? JSON.parse(String(init.body)) : null, method: init?.method ?? "GET", path: `${url.pathname}${url.search}` });
    if (url.pathname.endsWith("/preview")) return json(runOncePreview);
    if (url.pathname.endsWith("/run-once")) return json(runOnceMutation, 202);
    if (url.pathname.endsWith("/review")) return json(acceptMutation);
    if (url.pathname.includes("planning-task-execution")) return json(taskExecution);
    return json(taskExecution);
  };
  try {
    assert.deepEqual(await readPlanningTaskExecution(nonAttentionTask.id), taskExecution);
    assert.deepEqual(await previewPlanningTaskRunOnce(nonAttentionTask.id, 1), runOncePreview);
    assert.deepEqual(await confirmPlanningTaskRunOnce(nonAttentionTask.id, 1, "key_alpha_123456", runOncePreview.confirmation_id), runOnceMutation);
    globalThis.fetch = async () => json(runOnceMutation, 200);
    assert.deepEqual(await confirmPlanningTaskRunOnce(nonAttentionTask.id, 1, "key_replay_12345", runOncePreview.confirmation_id), runOnceMutation);
    globalThis.fetch = async (input, init) => {
      const url = new URL(input.toString(), "http://127.0.0.1:8890"); calls.push({ body: init?.body ? JSON.parse(String(init.body)) : null, method: init?.method ?? "GET", path: `${url.pathname}${url.search}` });
      return json(acceptMutation);
    };
    assert.deepEqual(await reviewPlanningTaskExecution(nonAttentionTask.id, 1, "accept", null, "key_beta_1234567"), acceptMutation);
    assert.deepEqual(calls, [
      { body: null, method: "GET", path: "/api/agent-console/planning-task-execution?task_id=task_plain" },
      { body: { expected_revision: 1 }, method: "POST", path: "/api/planning/tasks/task_plain/execution/run-once/preview" },
      { body: { confirmation_id: runOncePreview.confirmation_id, expected_revision: 1, idempotency_key: "key_alpha_123456" }, method: "POST", path: "/api/planning/tasks/task_plain/execution/run-once" },
      { body: { action: "accept", expected_revision: 1, idempotency_key: "key_beta_1234567" }, method: "POST", path: "/api/planning/tasks/task_plain/execution/review" },
    ]);
  } finally { globalThis.fetch = original; }
});
