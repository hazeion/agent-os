import assert from "node:assert/strict";
import { test } from "node:test";

import { BridgeAgentAttachmentsError, enableBridgeAgentAttachments, readBridgeAgentAttachmentsEnableStatus } from "../src/lib/bridge-agent-attachments.ts";
import { createAgentAttachmentsEnableStatusHandler, createEnableAgentAttachmentsHandler } from "../src/lib/agent-attachments-route.ts";
import { PublicAgentAttachmentsError, enableAgentAttachments, readAgentAttachmentsEnableStatus } from "../src/lib/public-agent-attachments.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:8891", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const origin = "http://127.0.0.1:8890";
const agentId = "agent_direct";
const expected = ["run.message", "run.start"];
const payload = { schema_version: 1 as const, service: "mentat-local-bridge" as const, runtime: "python" as const, status: "ready" as const, agent: { id: agentId, name: "Direct Agent", runtime_type: "hermes" as const, system_role: "direct" as const, capabilities: ["run.attachments", "run.message", "run.start"] } };

test("attachment opt-in bridge uses one fixed Agent mutation and requires verified capability", async () => {
  const calls: Array<{ path: string; init?: RequestInit }> = [];
  const result = await enableBridgeAgentAttachments(agentId, expected, async (input, init) => { calls.push({ path: input.toString(), init }); return Response.json(payload); }, environment);
  assert.deepEqual(result, payload);
  assert.equal(calls[0].path, `http://127.0.0.1:8891/bridge/v1/agents/${agentId}/attachments/enable`);
  assert.equal(calls[0].init?.body, '{"expected_capabilities":["run.message","run.start"]}');
  const missing = { ...payload, agent: { ...payload.agent, capabilities: expected } };
  await assert.rejects(() => enableBridgeAgentAttachments(agentId, expected, async () => Response.json(missing), environment), (error: unknown) => error instanceof BridgeAgentAttachmentsError && error.code === "bridge_response_invalid");
  await assert.rejects(
    () => enableBridgeAgentAttachments(agentId, expected, async () => Response.json({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "unsupported" }, { status: 415 }), environment),
    (error: unknown) => error instanceof BridgeAgentAttachmentsError && error.code === "agent_attachments_unsupported",
  );
  await assert.rejects(() => enableBridgeAgentAttachments(agentId, ["run.start", "run.message"], async () => { throw new Error("must not call"); }, environment), (error: unknown) => error instanceof BridgeAgentAttachmentsError && error.code === "agent_attachments_invalid");
});

test("attachment opt-in availability is one safe Agent-scoped read", async () => {
  const statusPayload = { schema_version: 1 as const, service: "mentat-local-bridge" as const, runtime: "python" as const, status: "ready" as const, agent_id: agentId, state: "available" as const };
  const bridgeCalls: string[] = [];
  assert.deepEqual(await readBridgeAgentAttachmentsEnableStatus(agentId, async (input) => { bridgeCalls.push(input.toString()); return Response.json(statusPayload); }, environment), statusPayload);
  assert.deepEqual(bridgeCalls, [`http://127.0.0.1:8891/bridge/v1/agents/${agentId}/attachments/enable`]);

  const handler = createAgentAttachmentsEnableStatusHandler({ gatewayPort: "8890", read: async () => statusPayload });
  const response = await handler(new Request(`${origin}/api/x`, { headers: { Host: "127.0.0.1:8890" } }), { params: Promise.resolve({ agentId }) });
  assert.equal(response.status, 200);
  assert.equal(await readAgentAttachmentsEnableStatus(agentId, async () => Response.json(statusPayload)), "available");
});

test("attachment opt-in route enforces same origin and exact sorted stale-state body", async () => {
  const calls: unknown[] = [];
  const handler = createEnableAgentAttachmentsHandler({ gatewayPort: "8890", enable: async (...args) => { calls.push(args); return payload; } });
  const context = { params: Promise.resolve({ agentId }) };
  const request = (body: string, requestOrigin = origin) => new Request(`${origin}/api/agents/${agentId}/attachments/enable`, { method: "POST", headers: { Host: "127.0.0.1:8890", Origin: requestOrigin, "Content-Type": "application/json" }, body });
  assert.equal((await handler(request('{"expected_capabilities":["run.message","run.start"]}'), context)).status, 200);
  assert.deepEqual(calls, [[agentId, expected]]);
  assert.equal((await handler(request('{"expected_capabilities":["run.start","run.message"]}'), context)).status, 400);
  assert.equal((await handler(request('{"expected_capabilities":["run.message","run.start"],"enable":true}'), context)).status, 400);
  assert.equal((await handler(request('{"expected_capabilities":["run.message","run.start"]}', "http://attacker.example"), context)).status, 403);
  assert.equal(calls.length, 1);
});

test("attachment opt-in maps stale and unsupported states without automatic mutation", async () => {
  const context = { params: Promise.resolve({ agentId }) };
  const request = new Request(`${origin}/api/x`, { method: "POST", headers: { Host: "127.0.0.1:8890", Origin: origin, "Content-Type": "application/json" }, body: '{"expected_capabilities":["run.message","run.start"]}' });
  for (const [code, status] of [["agent_attachments_conflict", 409], ["agent_attachments_unsupported", 415]] as const) {
    const handler = createEnableAgentAttachmentsHandler({ gatewayPort: "8890", enable: async () => { throw new BridgeAgentAttachmentsError(code); } });
    assert.equal((await handler(request.clone(), context)).status, status);
  }
});

test("public attachment opt-in sends exact current capabilities and rejects unsafe responses", async () => {
  const calls: Array<{ path: string; init?: RequestInit }> = [];
  const agent = await enableAgentAttachments(agentId, expected, async (input, init) => { calls.push({ path: input.toString(), init }); return Response.json(payload); });
  assert.deepEqual(agent.capabilities, payload.agent.capabilities);
  assert.equal(calls[0].path, `/api/agents/${agentId}/attachments/enable`);
  assert.equal(calls[0].init?.body, '{"expected_capabilities":["run.message","run.start"]}');
  await assert.rejects(() => enableAgentAttachments(agentId, expected, async () => Response.json({ ...payload, agent: { ...payload.agent, runtime_ref: "private" } })), PublicAgentAttachmentsError);
  await assert.rejects(() => enableAgentAttachments(agentId, ["run.start", "run.message"], async () => { throw new Error("must not call"); }), (error: unknown) => error instanceof PublicAgentAttachmentsError && error.code === "invalid");
});
