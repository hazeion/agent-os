import assert from "node:assert/strict";
import test from "node:test";
import { projectLeadCapability } from "../src/lib/bridge-project-leads.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:43210", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
test("a valid full Agent registry remains readable through the bounded bridge", async () => {
  const choices = Array.from({ length: 128 }, (_, index) => ({ id: `agent_${String(index).padStart(3, "0")}${"x".repeat(115)}`,
    name: "🔧".repeat(120), context_bound: false, selection_token: "a".repeat(64) }));
  const data = { project_id: "project_garage", project_revision: 1, revision: 0, id: null, agent_id: null, agent_name: null,
    status: "unassigned", reasons: [], proposal_available: false, choices, clear_token: "b".repeat(64) };
  const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", data };
  assert.ok(new TextEncoder().encode(JSON.stringify(envelope)).length > 32768);
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    assert.equal(String(input), "http://127.0.0.1:43210/bridge/v1/project-leads/project?project_id=project_garage");
    assert.equal(init?.method, "GET");
    return Response.json(envelope);
  };
  assert.equal((await projectLeadCapability("project", { project_id: "project_garage" }, fetcher, environment)).choices.length, 128);
});
