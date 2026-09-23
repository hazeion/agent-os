import assert from "node:assert/strict";
import test from "node:test";
import { contextRequest, contextResult } from "../src/lib/project-context-contract.ts";
import { projectContextCapability, ProjectContextBridgeError } from "../src/lib/bridge-project-context.ts";

const contextId = `project_context_${"a".repeat(32)}`;
const attachmentId = `attachment_${"b".repeat(32)}`;
const request = { project_id: "project_garage" };
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:8889", MENTAT_BRIDGE_TOKEN: "x".repeat(43) };
const file = { id: attachmentId, name: "floorplan.md", mime_type: "text/markdown", kind: "text", byte_size: 4, state: "attached", created_at: "2026-09-22T00:00:00Z", expires_at: null, available: true };
const version = { id: contextId, revision: 1, created_at: 1790035200, project_id: request.project_id, brief: "Leave room for bicycles", retired: false, current: true, files: [file], prune_blocked: "current_version" };
const editor = { project: { id: request.project_id, name: "Garage", revision: 1, status: "active" }, current: version, versions: [{ id: contextId, revision: 1, created_at: version.created_at }], staged: [], grants: [] };
function envelope(data: unknown) { return { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", data }; }

test("Project inputs bind complete staging and reject widened private selectors", () => {
  const publish = { ...request, expected_project_revision: 1, expected_revision: 0, brief: "Garage goals", attachment_ids: [attachmentId], expected_staged_ids: [attachmentId] };
  assert.deepEqual(contextRequest("publish", publish), publish);
  for (const invalid of [{ ...publish, expected_staged_ids: null }, { ...publish, attachment_ids: [attachmentId, attachmentId] }, { ...publish, runtime_agent_ref: "default" }, { ...publish, expected_revision: Number.MAX_SAFE_INTEGER + 1 }, { ...publish, brief: "🚲".repeat(4097) }]) assert.throws(() => contextRequest("publish", invalid));
  assert.throws(() => contextRequest("file", { ...request, context_id: contextId, attachment_id: attachmentId }));
  assert.throws(() => contextRequest("grant-confirm", { ...request, context_id: contextId, agent_id: "agent_research", confirmation_id: "f".repeat(64), confirmed: false }));
  assert.deepEqual(contextRequest("history", {}), {});
});

test("safe projections reject private fields, mismatched targets, duplicates and excess grants", () => {
  assert.deepEqual(contextResult("project", editor, request), editor);
  assert.deepEqual(contextResult("project", { ...editor, project: { ...editor.project, status: "paused" } }, request).project.status, "paused");
  const grant = { agent_id: "agent_research", context_id: contextId, revision: 1, state: "active", reason: null };
  assert.deepEqual(contextResult("project", { ...editor, grants: [grant] }, request).grants, [grant]);
  const badValues = [
    { ...editor, project: { ...editor.project, id: "project_other" } },
    { ...editor, current: { ...version, files: [{ ...file, blob_id: "private" }] } },
    { ...editor, current: { ...version, files: [file, file] } },
    { ...editor, grants: [grant, grant] },
    { ...editor, grants: Array.from({ length: 129 }, (_, index) => ({ ...grant, agent_id: `agent_${index}` })) },
    { ...editor, current: { ...version, retired: true } },
  ];
  for (const value of badValues) assert.throws(() => contextResult("project", value, request));
  assert.throws(() => contextResult("version", version, { context_id: `project_context_${"c".repeat(32)}` }));
});

test("full-size upload validates within the existing image limit", () => {
  const encoded = Buffer.alloc(10 * 1024 * 1024).toString("base64");
  assert.equal(contextRequest("upload", { ...request, expected_project_revision: 1, name: "floorplan.png", content_type: "image/png", content_base64: encoded }).content_base64, encoded);
  assert.throws(() => contextRequest("upload", { ...request, expected_project_revision: 1, name: "floorplan.png", content_type: "image/png", content_base64: encoded + "AAAA" }));
});

test("fixed bridge uses GET for reads, POST for writes and rejects redirects", async () => {
  await projectContextCapability("project", request, async (url, init) => {
    assert.equal(String(url), "http://127.0.0.1:8889/bridge/v1/project-context/project?project_id=project_garage");
    assert.equal(init?.method, "GET"); assert.equal(init?.body, undefined); assert.equal(init?.redirect, "error");
    assert.equal(new Headers(init?.headers).get("X-Mentat-Bridge-Token"), environment.MENTAT_BRIDGE_TOKEN);
    return Response.json(envelope(editor));
  }, environment);
  await projectContextCapability("discard", { ...request, expected_project_revision: 1, attachment_id: attachmentId }, async (_url, init) => {
    assert.equal(init?.method, "POST"); assert.equal(JSON.parse(String(init?.body)).attachment_id, attachmentId);
    return Response.json(envelope({ discarded: true }));
  }, environment);
});

test("invalid requests and origins never reach private transport", async () => {
  let calls = 0; const transport = async () => { calls++; return Response.json({}); };
  await assert.rejects(projectContextCapability("project", { ...request, path: "private" }, transport, environment));
  for (const origin of ["https://127.0.0.1:8889", "http://localhost:8889", "http://example.com:8889", "http://127.0.0.1:8889/private", "http://user@127.0.0.1:8889"]) await assert.rejects(projectContextCapability("project", request, transport, { ...environment, MENTAT_BRIDGE_ORIGIN: origin }));
  assert.equal(calls, 0);
});

test("bridge rejects private data, oversized streams and malformed file bytes", async () => {
  await assert.rejects(projectContextCapability("project", request, async () => Response.json(envelope({ ...editor, runtime_ref: "private" })), environment));
  await assert.rejects(projectContextCapability("project", request, async () => new Response(" ".repeat(512 * 1024 + 1), { headers: { "Content-Type": "application/json" } }), environment));
  const input = { context_id: contextId, attachment_id: attachmentId };
  const valid = { file, content_base64: Buffer.from("plan").toString("base64") };
  assert.deepEqual(await projectContextCapability("file", input, async () => Response.json(envelope(valid)), environment), valid);
  for (const encoded of ["!!!!!!!!", "cGxhbg=A", "cGxhbh=="]) await assert.rejects(projectContextCapability("file", input, async () => Response.json(envelope({ ...valid, content_base64: encoded })), environment));
});

test("bounded failures remain actionable and raw errors stay private", async () => {
  await assert.rejects(projectContextCapability("project", request, async () => Response.json({ schema_version: 1, status: "stale" }, { status: 409 }), environment), (error: unknown) => error instanceof ProjectContextBridgeError && error.code === "stale" && error.status === 409);
  await assert.rejects(projectContextCapability("project", request, async () => Response.json({ schema_version: 1, status: "private path secret" }, { status: 503 }), environment), (error: unknown) => error instanceof ProjectContextBridgeError && error.code === "invalid_response" && !error.message.includes("secret"));
});
