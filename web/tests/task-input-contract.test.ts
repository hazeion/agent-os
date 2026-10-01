import assert from "node:assert/strict";
import test from "node:test";
import { taskInputEditor, taskInputRequest, taskInputPublished, retiredTaskInputHistory, taskInputPrunePreview, taskInputPruned } from "../src/lib/task-input-contract.ts";
import { readBridgeTaskInputs, publishBridgeTaskInputs, readBridgeRetiredTaskInputs, previewBridgeTaskInputPrune, confirmBridgeTaskInputPrune, TaskInputBridgeError } from "../src/lib/bridge-task-inputs.ts";
import { createTaskInputRoute } from "../src/lib/task-input-route.ts";

const inputId = `task_input_${"a".repeat(32)}`, contextId = `project_context_${"b".repeat(32)}`, attachmentId = `attachment_${"c".repeat(32)}`;
const body = { task_id: "task_research", project_id: "project_garage", agent_id: "agent_research", expected_task_revision: 1, expected_input_revision: 0, context_id: contextId, expected_grant_revision: 1, expected_task_token: "f".repeat(64), instructions: "Use the supplied dimensions.", attachment_ids: [attachmentId] };
const file = { id: attachmentId, name: "floorplan.md", mime_type: "text/markdown", kind: "text", byte_size: 30, state: "attached", created_at: "2026-09-22T00:00:00Z", expires_at: null, available: true };
const eligible = { id: contextId, revision: 1, brief: "Keep bicycles clear", created_at: 1790035200, project_id: body.project_id, retired: false, current: true, files: [file], prune_blocked: "current_version" };
const version = { id: inputId, revision: 1, task_revision: 1, agent_id: body.agent_id, context_id: contextId, context_revision: 1, project_brief: eligible.brief, grant_revision: 1, instructions: body.instructions, created_at: 1790035200, files: [file] };
const editor = { task: { id: body.task_id, title: "Research garage organization", revision: 1, project_id: body.project_id, project_status: "active", assigned_agent_id: body.agent_id }, input_revision: 1, expected_task_token: body.expected_task_token, version, versions: [{ id: inputId, revision: 1, context_id: contextId, created_at: version.created_at }], eligible_contexts: [{ context: eligible, grant_revision: 1 }] };
const envelope = (data: unknown) => ({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", data });
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:8891", MENTAT_BRIDGE_TOKEN: "x".repeat(43) };
const origin = "http://127.0.0.1:8890", path = "/api/planning/tasks/task_research/inputs";
const headers = { Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json" };
const routeContext = { params: Promise.resolve({ taskId: "task_research", inputId }) };
function request(value: unknown) { return new Request(origin + path, { method: "POST", headers, body: JSON.stringify(value) }); }

test("exact Task input request binds canonical IDs and rejects widened authority", () => {
  assert.deepEqual(taskInputRequest(body), body);
  for (const invalid of [{ ...body, runtime_agent_ref: "default" }, { ...body, expected_task_revision: true }, { ...body, expected_task_token: "private" }, { ...body, attachment_ids: [attachmentId, attachmentId] }, { ...body, attachment_ids: null }, { ...body, instructions: "🚲".repeat(4097) }, { ...body, instructions: "\ud800" }]) assert.throws(() => taskInputRequest(invalid));
  assert.deepEqual(taskInputPublished({ input_id: inputId, revision: 1 }, body), { input_id: inputId, revision: 1 });
  assert.throws(() => taskInputPublished({ input_id: inputId, revision: 2 }, body));
});

test("editor projection includes only bounded safe versions for this Task", () => {
  assert.deepEqual(taskInputEditor(editor, body.task_id), editor);
  for (const invalid of [{ ...editor, binding_digest: "private" }, { ...editor, task: { ...editor.task, id: "task_other" } }, { ...editor, version: { ...version, binding_digest: "private" } }, { ...editor, eligible_contexts: [{ context: { ...eligible, project_id: "project_other" }, grant_revision: 1 }] }, { ...editor, versions: [editor.versions[0], editor.versions[0]] }]) assert.throws(() => taskInputEditor(invalid, body.task_id));
  assert.throws(() => taskInputEditor(editor, body.task_id, `task_input_${"d".repeat(32)}`));
});

test("private bridge has fixed loopback paths and rejects private projections", async () => {
  await readBridgeTaskInputs(body.task_id, undefined, async (url, init) => { assert.equal(String(url), "http://127.0.0.1:8891/bridge/v1/task-inputs/task?task_id=task_research"); assert.equal(init?.method, "GET"); assert.equal(init?.redirect, "error"); return Response.json(envelope(editor)); }, environment);
  await publishBridgeTaskInputs(body, async (url, init) => { assert.equal(new URL(String(url)).pathname, "/bridge/v1/task-inputs/publish"); assert.equal(init?.method, "POST"); assert.deepEqual(JSON.parse(String(init?.body)), body); return Response.json(envelope({ input_id: inputId, revision: 1 })); }, environment);
  await assert.rejects(readBridgeTaskInputs(body.task_id, undefined, async () => Response.json(envelope({ ...editor, private_ref: "secret" })), environment), (error: unknown) => error instanceof TaskInputBridgeError && error.code === "invalid_response");
  await assert.rejects(readBridgeTaskInputs(body.task_id, undefined, async () => Response.json({ schema_version: 1, status: "revision_conflict" }, { status: 409 }), environment), (error: unknown) => error instanceof TaskInputBridgeError && error.code === "revision_conflict");
  await assert.rejects(publishBridgeTaskInputs(body, async () => Response.json({ schema_version: 1, status: "project_unavailable" }, { status: 409 }), environment), (error: unknown) => error instanceof TaskInputBridgeError && error.code === "project_unavailable" && error.status === 409);
});

test("website routes bind path IDs before private transport and require same origin", async () => {
  const calls: unknown[] = [];
  const publish = (async (value: unknown) => { calls.push(value); return { input_id: inputId, revision: 1 }; }) as typeof publishBridgeTaskInputs;
  const handler = createTaskInputRoute("publish", { publish, gatewayPort: "8890" });
  assert.equal((await handler(request(Object.fromEntries(Object.entries(body).filter(([key]) => key !== "task_id"))), routeContext)).status, 200);
  assert.deepEqual(calls, [body]);
  assert.equal((await handler(request(body), routeContext)).status, 400);
  assert.equal((await handler(request({ ...body, task_id: undefined, raw_path: "private" }), routeContext)).status, 400);
  assert.equal((await handler(new Request(origin + path, { method: "POST", headers: { ...headers, Origin: "https://evil.example", "Sec-Fetch-Site": "cross-site" }, body: JSON.stringify(body) }), routeContext)).status, 403);
  assert.equal(calls.length, 1);
});

test("retired history and prune projections bind one exact version", async () => {
  const summary = { versions: [{ id: inputId, revision: 1, created_at: version.created_at, summary: "Garage layout" }] };
  assert.deepEqual(retiredTaskInputHistory(summary), summary);
  assert.throws(() => retiredTaskInputHistory({ versions: [{ ...summary.versions[0], runtime_ref: "private" }] }));
  const preview = { input_id: inputId, revision: 1, file_count: 1, confirmation_id: "f".repeat(64) };
  assert.deepEqual(taskInputPrunePreview(preview, inputId), preview);
  assert.throws(() => taskInputPrunePreview({ ...preview, file_count: 9 }, inputId));
  assert.deepEqual(taskInputPruned({ pruned: true }), { pruned: true });
  await readBridgeRetiredTaskInputs(async (url, init) => { assert.equal(String(url), "http://127.0.0.1:8891/bridge/v1/task-inputs/retired-history"); assert.equal(init?.method, "GET"); return Response.json(envelope(summary)); }, environment);
  await previewBridgeTaskInputPrune(inputId, async (url, init) => { assert.equal(new URL(String(url)).pathname, "/bridge/v1/task-inputs/prune-preview"); assert.deepEqual(JSON.parse(String(init?.body)), { input_id: inputId }); return Response.json(envelope(preview)); }, environment);
  await confirmBridgeTaskInputPrune(inputId, preview.confirmation_id, async (url, init) => { assert.equal(new URL(String(url)).pathname, "/bridge/v1/task-inputs/prune-confirm"); assert.deepEqual(JSON.parse(String(init?.body)), { input_id: inputId, confirmation_id: preview.confirmation_id, confirmed: true }); return Response.json(envelope({ pruned: true })); }, environment);
});
