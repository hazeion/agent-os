import assert from "node:assert/strict";
import test from "node:test";
import { projectInputCapability, ProjectInputBridgeError } from "../src/lib/bridge-project-planning-inputs.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:43210", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready" };
const editor = { project: { id: "project_garage", name: "Garage", revision: 1, status: "active" },
  lead: { id: null, revision: 0, agent_id: null, agent_name: null, status: "unassigned", reasons: [] },
  context: null, grant_revision: null, input_revision: 0, scope_token: "b".repeat(64), selection_token: "c".repeat(64),
  save_available: false, version: null, versions: [] };

test("Project input bridge calls one fixed private read and rejects widened output", async () => {
  let calls = 0;
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls++; assert.equal(String(input), "http://127.0.0.1:43210/bridge/v1/project-planning-inputs/project?project_id=project_garage");
    assert.equal(init?.method, "GET");
    return Response.json({ ...envelope, data: editor });
  };
  assert.equal((await projectInputCapability("project", { project_id: "project_garage" }, fetcher, environment)).input_revision, 0);
  assert.equal(calls, 1);
  await assert.rejects(() => projectInputCapability("project", { project_id: "project_garage", runtime_ref: "private" }, fetcher, environment),
    (error: unknown) => error instanceof ProjectInputBridgeError && error.status === 400);
  assert.equal(calls, 1);
  await assert.rejects(() => projectInputCapability("project", { project_id: "project_garage" }, async () => Response.json({ ...envelope, data: { ...editor, binding_digest: "private" } }), environment),
    (error: unknown) => error instanceof ProjectInputBridgeError && error.status === 502);
});
