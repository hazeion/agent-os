import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeConversationsError,
  createBridgeConversation,
  fetchBridgeConversation,
  fetchBridgeConversations,
} from "../src/lib/bridge-conversations.ts";

const environment = {
  MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152",
  MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars",
};
const agent = {
  capabilities: ["run.events", "run.message", "run.start", "run.status", "run.stop"],
  id: "agent_direct",
  name: "Direct Agent",
  runtime_type: "codex",
  system_role: "direct" as const,
};
const conversation = {
  agent_id: agent.id,
  archived_at: null,
  created_at: "2026-08-25T12:00:00Z",
  id: "conv_abc123",
  revision: 1,
  state: "active" as const,
  title: "New conversation",
  title_source: "default" as const,
  updated_at: "2026-08-25T12:00:00Z",
};
const detail = {
  agent,
  conversation,
  current_run: null,
  messages: [],
  next_message_cursor: null,
  runtime: "python" as const,
  schema_version: 1 as const,
  service: "mentat-local-bridge" as const,
  status: "ready" as const,
};
const list = {
  agents: [agent],
  conversations: [conversation],
  count: 1,
  direct_agent_id: agent.id,
  next_cursor: null,
  runtime: "python" as const,
  schema_version: 1 as const,
  service: "mentat-local-bridge" as const,
  status: "ready" as const,
};

test("Conversation bridge uses fixed paths and exact create bodies", async () => {
  const calls: Array<{ url: string; method: string; body: string | undefined }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: input.toString(), method: init?.method ?? "", body: init?.body?.toString() });
    const isDetail = input.toString().includes("/conv_");
    return new Response(JSON.stringify(init?.method === "POST" || isDetail ? detail : list), {
      headers: { "Content-Type": "application/json" },
      status: init?.method === "POST" ? 201 : 200,
    });
  };

  await fetchBridgeConversations(fetcher, environment);
  await createBridgeConversation(agent.id, fetcher, environment);
  await fetchBridgeConversation("conv_abc123", null, fetcher, environment);

  assert.deepEqual(calls.map(({ url, method, body }) => ({ url, method, body })), [
    { url: "http://127.0.0.1:49152/bridge/v1/conversations", method: "GET", body: undefined },
    { url: "http://127.0.0.1:49152/bridge/v1/conversations", method: "POST", body: '{"agent_id":"agent_direct"}' },
    { url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_abc123", method: "GET", body: undefined },
  ]);
});

test("Conversation bridge returns detached safe data and rejects private fields", async () => {
  const result = await fetchBridgeConversation(
    "conv_abc123",
    null,
    async () => new Response(JSON.stringify(detail), { headers: { "Content-Type": "application/json" } }),
    environment,
  );
  assert.deepEqual(result, detail);
  assert.notEqual(result.agent, detail.agent);
  await assert.rejects(
    fetchBridgeConversations(
      async () => new Response(JSON.stringify({ ...list, agents: [{ ...agent, runtime_agent_ref: "private" }] }), { headers: { "Content-Type": "application/json" } }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
});

test("Conversation bridge maps fixed failures and bounds pagination", async () => {
  const unavailable = {
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "unavailable",
  };
  await assert.rejects(
    fetchBridgeConversations(async () => Response.json(unavailable, { status: 503 }), environment),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_unavailable",
  );
  await assert.rejects(
    fetchBridgeConversation("conv_abc123", "0", async () => Response.json(detail), environment),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "conversation_id_invalid",
  );
  await assert.rejects(
    fetchBridgeConversation("conv_abc123", null, async () => new Response("x".repeat(3_000_001), { headers: { "Content-Type": "application/json" } }), environment),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
});
