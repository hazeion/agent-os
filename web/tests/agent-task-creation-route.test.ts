import assert from "node:assert/strict";
import { test } from "node:test";

import { BridgeAgentTaskCreationError, enableBridgeAgentTaskCreation, readBridgeAgentTaskCreationStatus } from "../src/lib/bridge-agent-task-creation.ts";
import { createAgentTaskCreationStatusHandler, createEnableAgentTaskCreationHandler } from "../src/lib/agent-task-creation-route.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:8891", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const origin = "http://127.0.0.1:8890";
const agentId = "agent_direct";
const expected = ["run.message", "run.start", "task.create"];
const payload = { schema_version: 1 as const, service: "mentat-local-bridge" as const, runtime: "python" as const, status: "ready" as const, agent: { id: agentId, name: "Direct Agent", runtime_type: "codex" as const, system_role: "direct" as const, capabilities: expected } };

test("task-creation opt-in uses one fixed Codex Agent mutation", async () => {
  const calls: Array<{ path: string; init?: RequestInit }> = [];
  const result = await enableBridgeAgentTaskCreation(agentId, ["run.message", "run.start"], async (input, init) => { calls.push({ path: input.toString(), init }); return Response.json(payload); }, environment);
  assert.deepEqual(result, payload.agent);
  assert.equal(calls[0].path, `http://127.0.0.1:8891/bridge/v1/agents/${agentId}/task-creation/enable`);
  assert.equal(calls[0].init?.body, '{"expected_capabilities":["run.message","run.start"]}');
  await assert.rejects(() => enableBridgeAgentTaskCreation(agentId, ["run.start", "run.message"], async () => { throw new Error("must not call"); }, environment), (error: unknown) => error instanceof BridgeAgentTaskCreationError && error.code === "invalid");
  await assert.rejects(() => enableBridgeAgentTaskCreation(agentId, ["run.message", "run.start"], async () => Response.json({ ...payload, agent: { ...payload.agent, capabilities: ["run.message", "run.start"] } }), environment), (error: unknown) => error instanceof BridgeAgentTaskCreationError && error.code === "invalid_response");
});

test("task-creation routes enforce same-origin requests and exact stale-state body", async () => {
  const calls: unknown[] = [];
  const handler = createEnableAgentTaskCreationHandler({ gatewayPort: "8890", enable: async (...args) => { calls.push(args); return payload.agent; } });
  const context = { params: Promise.resolve({ agentId }) };
  const request = (body: string, requestOrigin = origin) => new Request(`${origin}/api/agents/${agentId}/task-creation/enable`, { method: "POST", headers: { Host: "127.0.0.1:8890", Origin: requestOrigin, "Content-Type": "application/json" }, body });
  assert.equal((await handler(request('{"expected_capabilities":["run.message","run.start"]}'), context)).status, 200);
  assert.deepEqual(calls, [[agentId, ["run.message", "run.start"]]]);
  assert.equal((await handler(request('{"expected_capabilities":["run.start","run.message"]}'), context)).status, 400);
  assert.equal((await handler(request('{"expected_capabilities":["run.message","run.start"],"enable":true}'), context)).status, 400);
  assert.equal((await handler(request('{"expected_capabilities":["run.message","run.start"]}', "http://attacker.example"), context)).status, 403);
  assert.equal(calls.length, 1);
});

test("task-creation availability remains a bounded Agent-scoped read", async () => {
  const state = "available" as const;
  const bridgeCalls: string[] = [];
  assert.equal(await readBridgeAgentTaskCreationStatus(agentId, async (input) => { bridgeCalls.push(input.toString()); return Response.json({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", agent_id: agentId, state }); }, environment), state);
  assert.deepEqual(bridgeCalls, [`http://127.0.0.1:8891/bridge/v1/agents/${agentId}/task-creation/enable`]);
  const handler = createAgentTaskCreationStatusHandler({ gatewayPort: "8890", read: async () => state });
  const response = await handler(new Request(`${origin}/api/x`, { headers: { Host: "127.0.0.1:8890" } }), { params: Promise.resolve({ agentId }) });
  assert.equal(response.status, 200);
  assert.equal((await response.json() as { state: string }).state, state);
});

test("task-creation route maps fixed safe failures", async () => {
  const context = { params: Promise.resolve({ agentId }) };
  const request = new Request(`${origin}/api/x`, { method: "POST", headers: { Host: "127.0.0.1:8890", Origin: origin, "Content-Type": "application/json" }, body: '{"expected_capabilities":["run.message","run.start"]}' });
  for (const [code, status] of [["conflict", 409], ["unsupported", 415], ["unavailable", 503]] as const) {
    const handler = createEnableAgentTaskCreationHandler({ gatewayPort: "8890", enable: async () => { throw new BridgeAgentTaskCreationError(code); } });
    assert.equal((await handler(request.clone(), context)).status, status);
  }
});
