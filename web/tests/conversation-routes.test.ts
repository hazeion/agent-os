import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeConversationsError,
  type PublicCodexReadiness,
  type PublicConversationTurnSubmission,
} from "../src/lib/bridge-conversations.ts";
import { createCodexReadinessGetHandler } from "../src/lib/codex-readiness-route.ts";
import { createConversationTurnPostHandler } from "../src/lib/conversation-turn-route.ts";

const origin = "http://127.0.0.1:8890";
const requestHeaders = {
  "Content-Type": "application/json",
  Host: "127.0.0.1:8890",
  Origin: origin,
  "Sec-Fetch-Site": "same-origin",
};

function turnRequest(body: BodyInit, requestOrigin = origin) {
  return new Request(`${origin}/api/conversations/conv_route/turns`, {
    body,
    headers: { ...requestHeaders, Origin: requestOrigin },
    method: "POST",
  });
}

const submitted: PublicConversationTurnSubmission = {
  conversation: {
    agent_id: "agent_direct",
    archived_at: null,
    created_at: "2026-08-26T12:00:00Z",
    id: "conv_route",
    revision: 2,
    state: "active",
    title: "Route proof",
    title_source: "first_prompt",
    updated_at: "2026-08-26T12:01:00Z",
  },
  disposition: "accepted",
  duplicate: false,
  message: {
    content: { parts: [{ text: "Route proof", type: "text" }], schema_version: 1 },
    conversation_id: "conv_route",
    created_at: "2026-08-26T12:01:00Z",
    id: "msg_route",
    revision: 1,
    role: "user",
    run_id: "run_route",
    sequence: 1,
    state: "accepted",
    updated_at: "2026-08-26T12:01:00Z",
  },
  run: { id: "run_route", partial: false, status: "starting", updated_at: "2026-08-26T12:01:00Z" },
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  status: "ready",
  turn: {
    attempt_count: 1,
    blocked_reason: null,
    conversation_id: "conv_route",
    created_at: "2026-08-26T12:01:00Z",
    id: "turn_route",
    latest_run_id: "run_route",
    queue_ordinal: 1,
    revision: 2,
    state: "consumed",
    updated_at: "2026-08-26T12:01:00Z",
    user_message_id: "msg_route",
  },
};

test("Conversation Turn route executes exact same-origin admission and duplicate mappings", async () => {
  const calls: string[][] = [];
  const handler = createConversationTurnPostHandler({
    gatewayPort: "8890",
    submitTurn: async (...values) => {
      calls.push(values);
      return submitted;
    },
  });
  const response = await handler(
    turnRequest('{"idempotency_key":"conversation-route-key","text":"Route proof"}'),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(response.status, 202);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.deepEqual(calls, [["conv_route", "Route proof", "conversation-route-key"]]);
  assert.deepEqual(await response.json(), submitted);

  const duplicate = await createConversationTurnPostHandler({
    gatewayPort: "8890",
    submitTurn: async () => ({ ...submitted, duplicate: true }),
  })(
    turnRequest('{"idempotency_key":"conversation-route-key","text":"Route proof"}'),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(duplicate.status, 200);
});

test("Conversation Turn route rejects foreign origins, malformed bodies, and maps fixed failures", async () => {
  let calls = 0;
  const accepted = createConversationTurnPostHandler({
    gatewayPort: "8890",
    submitTurn: async () => { calls += 1; return submitted; },
  });
  const forbidden = await accepted(
    turnRequest('{"idempotency_key":"conversation-route-key","text":"Route proof"}', "https://attacker.example"),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(forbidden.status, 403);
  assert.equal(calls, 0);

  const malformed = await accepted(
    turnRequest(new Uint8Array([0x80])),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(malformed.status, 400);
  assert.deepEqual(await malformed.json(), { schema_version: 1, status: "invalid" });
  assert.equal(calls, 0);

  const mappings = new Map<string, [number, string]>([
    ["conversation_active_run", [409, "active_run"]],
    ["conversation_capacity_unavailable", [409, "capacity_unavailable"]],
    ["conversation_idempotency_conflict", [409, "idempotency_conflict"]],
    ["codex_cli_missing", [409, "cli_missing"]],
    ["codex_sign_in_required", [409, "sign_in_required"]],
    ["conversation_not_found", [404, "not_found"]],
    ["bridge_unavailable", [503, "unavailable"]],
  ]);
  for (const [code, [status, state]] of mappings) {
    const response = await createConversationTurnPostHandler({
      gatewayPort: "8890",
      submitTurn: async () => { throw new BridgeConversationsError(code); },
    })(
      turnRequest('{"idempotency_key":"conversation-route-key","text":"Route proof"}'),
      { params: Promise.resolve({ conversationId: "conv_route" }) },
    );
    assert.equal(response.status, status, code);
    assert.deepEqual(await response.json(), { schema_version: 1, status: state });
  }
});

test("Codex readiness route executes readiness transitions and same-origin protection", async () => {
  for (const state of ["cli_missing", "sign_in_required", "ready", "unavailable"] as const) {
    const payload: PublicCodexReadiness = {
      runtime: "python",
      schema_version: 1,
      service: "mentat-local-bridge",
      setup_command: state === "sign_in_required" ? "codex login" : null,
      state,
      status: "ready",
    };
    const response = await createCodexReadinessGetHandler({
      fetchReadiness: async () => payload,
      gatewayPort: "8890",
    })(new Request(`${origin}/api/codex-readiness`, { headers: { Host: "127.0.0.1:8890" } }));
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), payload);
  }
  const unavailable = await createCodexReadinessGetHandler({
    fetchReadiness: async () => { throw new BridgeConversationsError("bridge_unavailable"); },
    gatewayPort: "8890",
  })(new Request(`${origin}/api/codex-readiness`, { headers: { Host: "127.0.0.1:8890" } }));
  assert.equal(unavailable.status, 503);
  assert.deepEqual(await unavailable.json(), { schema_version: 1, status: "unavailable" });
});
