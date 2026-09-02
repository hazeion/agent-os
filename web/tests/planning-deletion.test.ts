import assert from "node:assert/strict";
import test from "node:test";

import { confirmBridgePlanningDeletion, previewBridgePlanningDeletion } from "../src/lib/bridge-planning-deletion.ts";
import { createPlanningDeletionConfirmHandler, createPlanningDeletionPreviewHandler } from "../src/lib/planning-deletion-route.ts";
import { confirmPlanningDeletion, parsePlanningDeletionMutation, parsePlanningDeletionPreview, previewPlanningDeletion, PublicPlanningDeletionError } from "../src/lib/public-planning-deletion.ts";
import { BridgePlanningError } from "../src/lib/bridge-planning.ts";

const envelope = { runtime: "python" as const, schema_version: 1 as const, service: "mentat-local-bridge" as const, status: "ready" as const };
const counts = { artifacts: 2, conversations: 1, projects: 1, runs: 1, tasks: 3 };
const preview = { ...envelope, affected: counts, confirmation_id: "a".repeat(64), has_active_runs: true, target_id: "task_alpha", target_kind: "task" as const };
const deletion = { ...envelope, action: "delete" as const, deletion: counts, target_id: "task_alpha", target_kind: "task" as const };
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const headers = { Host: "127.0.0.1:8890", Origin: "http://127.0.0.1:8890", "Sec-Fetch-Site": "same-origin" };
const context = { params: Promise.resolve({ taskId: "task_alpha" }) };
function json(value: unknown, status = 200) { return Response.json(value, { headers: { "content-type": "application/json" }, status }); }
function post(path: string, value: unknown) { return new Request(`http://127.0.0.1:8890${path}`, { body: JSON.stringify(value), headers: { ...headers, "Content-Type": "application/json" }, method: "POST" }); }

test("deletion parsers accept only exact content-free count projections", () => {
  assert.deepEqual(parsePlanningDeletionPreview(preview, "task", "task_alpha"), preview);
  assert.deepEqual(parsePlanningDeletionMutation(deletion, "task", "task_alpha"), deletion);
  for (const hostile of [
    { ...preview, task_title: "private" },
    { ...preview, affected: { ...counts, tasks: 0 } },
    { ...preview, target_id: "task_other" },
    { ...deletion, deletion: { ...counts, projects: 0 }, target_kind: "project", target_id: "project_alpha" },
    { ...deletion, confirmation_id: preview.confirmation_id },
  ]) assert.throws(() => "affected" in hostile ? parsePlanningDeletionPreview(hostile, "task", "task_alpha") : parsePlanningDeletionMutation(hostile, "task", "task_alpha"), PublicPlanningDeletionError);
});

test("deletion bridge uses the two exact private commands and rejects widened responses", async () => {
  const calls: Array<{ body: unknown; path: string }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(input.toString()); calls.push({ body: JSON.parse(String(init?.body)), path: url.pathname });
    return json(url.pathname.endsWith("/preview") ? preview : deletion);
  };
  assert.deepEqual(await previewBridgePlanningDeletion("task", "task_alpha", fetcher, environment), preview);
  assert.deepEqual(await confirmBridgePlanningDeletion("task", "task_alpha", preview.confirmation_id, fetcher, environment), deletion);
  assert.deepEqual(calls, [
    { body: { target_id: "task_alpha", target_kind: "task" }, path: "/bridge/v1/agent-console/planning-deletion/preview" },
    { body: { confirmation_id: preview.confirmation_id, confirmed: true, target_id: "task_alpha", target_kind: "task" }, path: "/bridge/v1/agent-console/planning-deletion/confirm" },
  ]);
  await assert.rejects(previewBridgePlanningDeletion("task", "task_alpha", async () => json({ ...preview, task_id: "private" }), environment), BridgePlanningError);
});

test("deletion API routes require same-origin exact preview and confirmation bodies", async () => {
  const previewHandler = createPlanningDeletionPreviewHandler("task", { gatewayPort: "8890", preview: async () => preview });
  const confirmHandler = createPlanningDeletionConfirmHandler("task", { gatewayPort: "8890", confirm: async () => deletion });
  assert.equal((await previewHandler(post("/api/planning/tasks/task_alpha/delete/preview", {}), context)).status, 200);
  assert.equal((await confirmHandler(post("/api/planning/tasks/task_alpha/delete", { confirmation_id: preview.confirmation_id, confirmed: true }), context)).status, 200);
  assert.equal((await previewHandler(post("/api/planning/tasks/task_alpha/delete/preview", { extra: true }), context)).status, 400);
  assert.equal((await confirmHandler(post("/api/planning/tasks/task_alpha/delete", { confirmation_id: preview.confirmation_id, confirmed: true, extra: true }), context)).status, 400);
  assert.equal((await previewHandler(new Request("http://127.0.0.1:8890/api/planning/tasks/task_alpha/delete/preview", { body: "{}", headers: { "Content-Type": "application/json", Host: "127.0.0.1:8890", Origin: "http://evil.invalid", "Sec-Fetch-Site": "cross-site" }, method: "POST" }), context)).status, 403);
});

test("public deletion clients use only named same-origin preview and confirmation paths", async () => {
  const original = globalThis.fetch; const calls: Array<{ body: unknown; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input.toString(), "http://127.0.0.1:8890");
    calls.push({ body: JSON.parse(String(init?.body)), path: url.pathname });
    return json(url.pathname.endsWith("/preview") ? preview : deletion);
  };
  try {
    assert.deepEqual(await previewPlanningDeletion("task", "task_alpha"), preview);
    assert.deepEqual(await confirmPlanningDeletion("task", "task_alpha", preview.confirmation_id), deletion);
    assert.deepEqual(calls, [
      { body: {}, path: "/api/planning/tasks/task_alpha/delete/preview" },
      { body: { confirmation_id: preview.confirmation_id, confirmed: true }, path: "/api/planning/tasks/task_alpha/delete" },
    ]);
  } finally { globalThis.fetch = original; }
});
