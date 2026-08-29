import assert from "node:assert/strict";
import test from "node:test";

import { createAgentConfigurationHandlers } from "../src/lib/agent-configuration-route.ts";

const configuration = {
  active_run: false,
  agent_id: "agent_builder",
  current: { effort: "runtime_default" as const, model: "gpt", provider: "openai" },
  efforts: [{ id: "runtime_default" as const, name: "Runtime default" as const }] as [{ id: "runtime_default"; name: "Runtime default" }],
  explanation: "",
  mutable: true,
  providers: [{ current: true, id: "openai", models: ["gpt"], name: "OpenAI" }],
  runtime_type: "hermes",
  schema_version: 1 as const,
  state: "ready" as const,
};
const envelope = { configuration, runtime: "python" as const, schema_version: 1 as const, service: "mentat-local-bridge" as const, status: "ready" as const };
const context = { params: Promise.resolve({ agentId: "agent_builder" }) };

function request(path: string, method = "GET", body?: string) {
  return new Request(`http://127.0.0.1:8888${path}`, { body, headers: { host: "127.0.0.1:8888", ...(body ? { "content-type": "application/json", origin: "http://127.0.0.1:8888", "sec-fetch-site": "same-origin" } : {}) }, method });
}

test("Agent configuration routes enforce same-origin exact bodies and targets", async () => {
  const calls: unknown[] = [];
  const handlers = createAgentConfigurationHandlers({
    gatewayPort: "8888",
    read: async (agentId: string) => { calls.push(["read", agentId]); return envelope; },
    preview: async (agentId: string, provider: string, model: string) => { calls.push(["preview", agentId, provider, model]); return { action: "configure", agent_id: agentId, confirmation_id: "provider_switch_" + "a".repeat(24), current: { model: "gpt", provider: "openai" }, message: "Next Run", requires_confirmation: true, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready", target: { effort: "runtime_default", model, provider, provider_name: "Anthropic" } }; },
    confirm: async (agentId: string, provider: string, model: string, confirmationId: string) => { calls.push(["confirm", agentId, provider, model, confirmationId]); return { action: "configure", agent_id: agentId, configuration: { ...configuration, current: { effort: "runtime_default", model, provider } }, message: "Verified", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }; },
  });
  assert.equal((await handlers.get(request("/api/agents/agent_builder/configuration"), context)).status, 200);
  assert.equal((await handlers.preview(request("/api/agents/agent_builder/configuration/preview", "POST", '{"provider":"anthropic","model":"claude"}'), context)).status, 200);
  const confirmationId = "provider_switch_" + "a".repeat(24);
  assert.equal((await handlers.confirm(request("/api/agents/agent_builder/configuration", "POST", JSON.stringify({ confirmation_id: confirmationId, provider: "anthropic", model: "claude" })), context)).status, 200);
  assert.deepEqual(calls, [["read", "agent_builder"], ["preview", "agent_builder", "anthropic", "claude"], ["confirm", "agent_builder", "anthropic", "claude", confirmationId]]);
  assert.equal((await handlers.preview(new Request("http://127.0.0.1:8888/api/agents/agent_builder/configuration/preview", { body: '{"provider":"anthropic","model":"claude"}', headers: { "content-type": "application/json", host: "127.0.0.1:8888", origin: "https://evil.example", "sec-fetch-site": "cross-site" }, method: "POST" }), context)).status, 403);
  assert.equal((await handlers.preview(request("/api/agents/agent_builder/configuration/preview", "POST", '{"provider":"anthropic","model":"claude","runtime_agent_ref":"private"}'), context)).status, 400);
});
