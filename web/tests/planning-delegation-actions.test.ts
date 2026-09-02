import assert from "node:assert/strict";
import test from "node:test";

import {
  confirmBridgePlanningTaskDelegation,
  confirmBridgePlanningTaskDelegationAction,
  fetchBridgePlanningTaskDelegationOptions,
  previewBridgePlanningTaskDelegation,
  previewBridgePlanningTaskDelegationAction,
  recoverBridgePlanningTaskDelegation,
  refreshBridgePlanningTaskDelegation,
} from "../src/lib/bridge-planning.ts";
import {
  createPlanningTaskDelegateHandler,
  createPlanningTaskDelegationActionHandler,
  createPlanningTaskDelegationActionPreviewHandler,
  createPlanningTaskDelegationOptionsHandler,
  createPlanningTaskDelegationPreviewHandler,
  createPlanningTaskDelegationRecoverHandler,
  createPlanningTaskDelegationRefreshHandler,
} from "../src/lib/planning-task-delegation-actions-route.ts";
import {
  parsePlanningTaskDelegationOptions,
  parsePlanningTaskDelegationPreview,
  confirmPlanningTaskDelegation,
  confirmPlanningTaskDelegationAction,
  previewPlanningTaskDelegation,
  previewPlanningTaskDelegationAction,
  readPlanningTaskDelegationOptions,
  recoverPlanningTaskDelegation,
  refreshPlanningTaskDelegation,
} from "../src/lib/public-planning-task-delegation-actions.ts";
import { PublicPlanningError } from "../src/lib/public-planning.ts";

const env = { runtime: "python" as const, schema_version: 1 as const, service: "mentat-local-bridge" as const, status: "ready" as const };
const task = { id: "task_alpha", revision: 3 };
const delegation = { artifact_count: 0, attempts: 1, available: true as const, last_outcome: null, last_synced_at: null, latest_question: null, review_state: "pending" as const, state: "ready_for_review" as const, summary: "Ready for review.", sync_state: "synced" as const, updated_at: "2026-09-02T12:00:00Z" };
const current = { ...env, delegation, task };
const options = { ...current, options: { available: true as const, boards: [{ id: "default", name: "Default" }], profiles: [{ id: "researcher", name: "Researcher" }], workspaces: ["scratch", "worktree"] as ["scratch", "worktree"] } };
const delegatePreview = { ...current, action: "delegate" as const, confirmation_id: `task_delegate_${"a".repeat(24)}`, effects: ["Create one Hermes task."], requires_confirmation: true as const, target: { board_id: "default", profile_id: "researcher", workspace: "scratch" as const } };
const acceptPreview = { ...current, action: "accept" as const, confirmation_id: `delegation_action_${"b".repeat(24)}`, effects: ["Accept the result."], requires_confirmation: true as const };
const mutation = { ...current, action: "delegate" as const, duplicate: false };
const recovery = { ...current, action: "delegate" as const, duplicate: false, recovered: true };
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const headers = { Host: "127.0.0.1:8890", Origin: "http://127.0.0.1:8890", "Sec-Fetch-Site": "same-origin" };
const context = { params: Promise.resolve({ taskId: task.id }) };
const key = "delegation-idempotency-0001";
function json(value: unknown, status = 200) { return Response.json(value, { headers: { "content-type": "application/json" }, status }); }
function post(path: string, value: unknown) { return new Request(`http://127.0.0.1:8890${path}`, { body: JSON.stringify(value), headers: { ...headers, "Content-Type": "application/json" }, method: "POST" }); }

test("delegation action parsers reject private fields and require a capability-scoped envelope", () => {
  assert.deepEqual(parsePlanningTaskDelegationOptions(options, task.id), options);
  assert.deepEqual(parsePlanningTaskDelegationPreview(delegatePreview, task.id), delegatePreview);
  assert.throws(() => parsePlanningTaskDelegationOptions({ ...options, connection_binding_id: "private" }, task.id), PublicPlanningError);
  assert.throws(() => parsePlanningTaskDelegationPreview({ ...delegatePreview, target: { ...delegatePreview.target, run_id: "private" } }, task.id), PublicPlanningError);
});

test("delegation bridge functions use only fixed paths and exact payloads", async () => {
  const calls: Array<{ path: string; body: unknown }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(input.toString()); const path = `${url.pathname}${url.search}`;
    calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (path.endsWith("/action/preview")) return json(acceptPreview);
    if (path.endsWith("/action")) return json({ ...mutation, action: "accept" });
    if (path.endsWith("/preview")) return json(delegatePreview);
    if (path.endsWith("/delegate")) return json(mutation, 201);
    if (path.endsWith("/refresh")) return json({ ...current, action: "refresh" });
    if (path.endsWith("/recover")) return json(recovery);
    return json(options);
  };
  await fetchBridgePlanningTaskDelegationOptions(task.id, fetcher, environment);
  await previewBridgePlanningTaskDelegation(task.id, 3, "researcher", "default", "scratch", "Cite sources.", "", fetcher, environment);
  await confirmBridgePlanningTaskDelegation(task.id, 3, "researcher", "default", "scratch", "Cite sources.", "", delegatePreview.confirmation_id, key, fetcher, environment);
  await previewBridgePlanningTaskDelegationAction(task.id, 3, "accept", null, fetcher, environment);
  await confirmBridgePlanningTaskDelegationAction(task.id, 3, "accept", null, acceptPreview.confirmation_id, key, fetcher, environment);
  await refreshBridgePlanningTaskDelegation(task.id, 3, fetcher, environment);
  await recoverBridgePlanningTaskDelegation(task.id, delegatePreview.confirmation_id, key, fetcher, environment);
  assert.deepEqual(calls.map((call) => call.path), [
    "/bridge/v1/agent-console/planning-task-delegation/options?task_id=task_alpha",
    "/bridge/v1/agent-console/planning-task-delegation/preview",
    "/bridge/v1/agent-console/planning-task-delegation/delegate",
    "/bridge/v1/agent-console/planning-task-delegation/action/preview",
    "/bridge/v1/agent-console/planning-task-delegation/action",
    "/bridge/v1/agent-console/planning-task-delegation/refresh",
    "/bridge/v1/agent-console/planning-task-delegation/recover",
  ]);
  assert.deepEqual(calls[2]?.body, { task_id: task.id, expected_revision: 3, profile_id: "researcher", board_id: "default", workspace: "scratch", instructions: "Cite sources.", context_pack_id: "", confirmation_id: delegatePreview.confirmation_id, idempotency_key: key });
});

test("delegation API routes reject extra or malformed browser input", async () => {
  const read = createPlanningTaskDelegationOptionsHandler({ gatewayPort: "8890", readOptions: async () => options });
  const preview = createPlanningTaskDelegationPreviewHandler({ gatewayPort: "8890", preview: async () => delegatePreview });
  const delegate = createPlanningTaskDelegateHandler({ gatewayPort: "8890", confirm: async () => mutation });
  const actionPreview = createPlanningTaskDelegationActionPreviewHandler({ gatewayPort: "8890", preview: async () => acceptPreview });
  const action = createPlanningTaskDelegationActionHandler({ gatewayPort: "8890", confirm: async () => ({ ...mutation, action: "accept" }) });
  const refresh = createPlanningTaskDelegationRefreshHandler({ gatewayPort: "8890", refresh: async () => ({ ...current, action: "refresh" as const }) });
  const recover = createPlanningTaskDelegationRecoverHandler({ gatewayPort: "8890", recover: async () => recovery });
  const intent = { expected_revision: 3, profile_id: "researcher", board_id: "default", workspace: "scratch", instructions: "Cite sources.", context_pack_id: "" };
  assert.equal((await read(new Request(`http://127.0.0.1:8890/api/agent-console/planning-task-delegation/options?task_id=${task.id}`, { headers }))).status, 200);
  assert.equal((await preview(post(`/api/planning/tasks/${task.id}/delegation/preview`, intent), context)).status, 200);
  assert.equal((await delegate(post(`/api/planning/tasks/${task.id}/delegation/delegate`, { ...intent, confirmation_id: delegatePreview.confirmation_id, idempotency_key: key }), context)).status, 201);
  assert.equal((await actionPreview(post(`/api/planning/tasks/${task.id}/delegation/action/preview`, { expected_revision: 3, action: "accept" }), context)).status, 200);
  assert.equal((await action(post(`/api/planning/tasks/${task.id}/delegation/action`, { expected_revision: 3, action: "accept", confirmation_id: acceptPreview.confirmation_id, idempotency_key: key }), context)).status, 200);
  assert.equal((await refresh(post(`/api/planning/tasks/${task.id}/delegation/refresh`, { expected_revision: 3 }), context)).status, 200);
  assert.equal((await recover(post(`/api/planning/tasks/${task.id}/delegation/recover`, { confirmation_id: delegatePreview.confirmation_id, idempotency_key: key }), context)).status, 200);
  assert.equal((await preview(post(`/api/planning/tasks/${task.id}/delegation/preview`, { ...intent, extra: true }), context)).status, 400);
  assert.equal((await action(post(`/api/planning/tasks/${task.id}/delegation/action`, { expected_revision: 3, action: "accept", note: "not accepted", confirmation_id: acceptPreview.confirmation_id, idempotency_key: key }), context)).status, 400);
  assert.equal((await read(new Request(`http://127.0.0.1:8890/api/agent-console/planning-task-delegation/options?task_id=${task.id}&extra=1`, { headers }))).status, 400);
});

test("public delegation clients use only named same-origin routes", async () => {
  const original = globalThis.fetch; const calls: Array<{ path: string; body: unknown }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), "http://127.0.0.1:8890");
    calls.push({ path: `${url.pathname}${url.search}`, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.pathname.endsWith("/options")) return json(options);
    if (url.pathname.endsWith("/action/preview")) return json(acceptPreview);
    if (url.pathname.endsWith("/action")) return json({ ...mutation, action: "accept" });
    if (url.pathname.endsWith("/preview")) return json(delegatePreview);
    if (url.pathname.endsWith("/delegate")) return json(mutation, 201);
    if (url.pathname.endsWith("/refresh")) return json({ ...current, action: "refresh" });
    return json(recovery);
  };
  try {
    await readPlanningTaskDelegationOptions(task.id);
    await previewPlanningTaskDelegation(task.id, 3, "researcher", "default", "scratch", "Cite sources.", "");
    await confirmPlanningTaskDelegation(task.id, 3, "researcher", "default", "scratch", "Cite sources.", "", delegatePreview.confirmation_id, key);
    await previewPlanningTaskDelegationAction(task.id, 3, "accept", null);
    await confirmPlanningTaskDelegationAction(task.id, 3, "accept", null, acceptPreview.confirmation_id, key);
    await refreshPlanningTaskDelegation(task.id, 3);
    await recoverPlanningTaskDelegation(task.id, delegatePreview.confirmation_id, key);
    assert.deepEqual(calls.map((call) => call.path), [
      "/api/agent-console/planning-task-delegation/options?task_id=task_alpha",
      "/api/planning/tasks/task_alpha/delegation/preview",
      "/api/planning/tasks/task_alpha/delegation/delegate",
      "/api/planning/tasks/task_alpha/delegation/action/preview",
      "/api/planning/tasks/task_alpha/delegation/action",
      "/api/planning/tasks/task_alpha/delegation/refresh",
      "/api/planning/tasks/task_alpha/delegation/recover",
    ]);
  } finally { globalThis.fetch = original; }
});
