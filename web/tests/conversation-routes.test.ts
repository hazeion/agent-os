import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeConversationsError,
  type PublicCodexReadiness,
  type PublicConversationQueueMutation,
  type PublicConversationSteerResult,
  type PublicConversationTurnSubmission,
} from "../src/lib/bridge-conversations.ts";
import { createCodexReadinessGetHandler } from "../src/lib/codex-readiness-route.ts";
import { createConversationTurnPostHandler } from "../src/lib/conversation-turn-route.ts";
import { createConversationQueueActionHandler } from "../src/lib/conversation-queue-route.ts";
import { createConversationArchiveHandler } from "../src/lib/conversation-archive-route.ts";
import { createConversationResumeHandler, createConversationRetryHandler } from "../src/lib/conversation-retry-route.ts";
import { createConversationSteerHandler } from "../src/lib/conversation-steer-route.ts";

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

test("Conversation queue routes bind both revisions and map stale conflicts", async () => {
  const mutation: PublicConversationQueueMutation = {
    conversation: submitted.conversation,
    disposition: "edited",
    message: { ...submitted.message, content: { parts: [{ text: "Edited route proof", type: "text" }], schema_version: 1 }, run_id: null, revision: 2 },
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
    turn: { ...submitted.turn, attempt_count: 0, id: "turn_queue", latest_run_id: null, state: "pending", user_message_id: submitted.message.id },
  };
  const calls: unknown[][] = [];
  const handler = createConversationQueueActionHandler("edit", {
    gatewayPort: "8890",
    mutate: async (...values) => { calls.push(values); return mutation; },
  });
  const response = await handler(
    new Request(`${origin}/api/conversations/conv_route/turns/turn_queue/edit`, {
      body: '{"expected_message_revision":2,"expected_revision":3,"text":"Edited route proof"}',
      headers: requestHeaders,
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route", turnId: "turn_queue" }) },
  );
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [["conv_route", "turn_queue", 3, 2, "Edited route proof"]]);
  assert.deepEqual(await response.json(), mutation);

  const malformed = await handler(
    new Request(`${origin}/api/conversations/conv_route/turns/turn_queue/edit`, {
      body: '{"expected_revision":3,"text":"Edited route proof"}',
      headers: requestHeaders,
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route", turnId: "turn_queue" }) },
  );
  assert.equal(malformed.status, 400);
  assert.equal(calls.length, 1);

  const stale = await createConversationQueueActionHandler("cancel", {
    gatewayPort: "8890",
    mutate: async () => { throw new BridgeConversationsError("conversation_conflict"); },
  })(
    new Request(`${origin}/api/conversations/conv_route/turns/turn_queue/cancel`, {
      body: '{"expected_message_revision":2,"expected_revision":3}',
      headers: requestHeaders,
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route", turnId: "turn_queue" }) },
  );
  assert.equal(stale.status, 409);
  assert.deepEqual(await stale.json(), { schema_version: 1, status: "conflict" });
});

test("Conversation archive route binds the exact revision and same-origin request", async () => {
  const archived = {
    action: "archive" as const,
    conversation: {
      ...submitted.conversation,
      archived_at: "2026-08-26T12:02:00Z",
      revision: 3,
      state: "archived" as const,
      updated_at: "2026-08-26T12:02:00Z",
    },
    runtime: "python" as const,
    schema_version: 1 as const,
    service: "mentat-local-bridge" as const,
    status: "ready" as const,
  };
  const calls: unknown[][] = [];
  const handler = createConversationArchiveHandler(true, {
    gatewayPort: "8890",
    mutate: async (...values) => { calls.push(values); return archived; },
  });
  const response = await handler(
    new Request(`${origin}/api/conversations/conv_route/archive`, {
      body: '{"expected_revision":2}',
      headers: requestHeaders,
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [["conv_route", 2, true]]);
  assert.deepEqual(await response.json(), archived);

  const forbidden = await handler(
    new Request(`${origin}/api/conversations/conv_route/archive`, {
      body: '{"expected_revision":2}',
      headers: { ...requestHeaders, Origin: "https://attacker.example" },
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(forbidden.status, 403);
  assert.equal(calls.length, 1);
});

test("Conversation Retry route binds one exact source Run and action key", async () => {
  const retried = {
    action: "retry" as const,
    conversation_id: "conv_route",
    duplicate: false,
    run: { id: "run_retry", partial: false, status: "starting", updated_at: "2026-08-26T12:02:00Z" },
    runtime: "python" as const,
    schema_version: 1 as const,
    service: "mentat-local-bridge" as const,
    source_run_id: "run_route",
    status: "ready" as const,
  };
  const calls: unknown[][] = [];
  const response = await createConversationRetryHandler({
    gatewayPort: "8890",
    retry: async (...values) => { calls.push(values); return retried; },
  })(
    new Request(`${origin}/api/conversations/conv_route/retry`, {
      body: '{"idempotency_key":"conversation-route-retry-key","source_run_id":"run_route"}',
      headers: requestHeaders,
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(response.status, 202);
  assert.deepEqual(calls, [["conv_route", "run_route", "conversation-route-retry-key"]]);
  assert.deepEqual(await response.json(), retried);

  const resumed = { ...retried, action: "resume" as const, run: { ...retried.run, id: "run_resume" } };
  const resumeResponse = await createConversationResumeHandler({
    gatewayPort: "8890",
    retry: async () => resumed,
  })(
    new Request(`${origin}/api/conversations/conv_route/resume`, {
      body: '{"idempotency_key":"conversation-route-resume-key","source_run_id":"run_route"}',
      headers: requestHeaders,
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(resumeResponse.status, 202);
  assert.equal((await resumeResponse.json()).action, "resume");
});

test("Conversation steer route is exact and preserves partial as an explicit failure", async () => {
  const steered: PublicConversationSteerResult = {
    action: "steer",
    conversation_id: "conv_route",
    disposition: "accepted",
    run_id: "run_route",
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
  };
  const calls: unknown[][] = [];
  const response = await createConversationSteerHandler({
    gatewayPort: "8890",
    steer: async (...values) => { calls.push(values); return steered; },
  })(
    new Request(`${origin}/api/conversations/conv_route/steer`, {
      body: '{"run_id":"run_route","text":"Use the exact route"}',
      headers: requestHeaders,
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [["conv_route", "run_route", "Use the exact route"]]);

  const partial = await createConversationSteerHandler({
    gatewayPort: "8890",
    steer: async () => { throw new BridgeConversationsError("conversation_partial"); },
  })(
    new Request(`${origin}/api/conversations/conv_route/steer`, {
      body: '{"run_id":"run_route","text":"Use the exact route"}',
      headers: requestHeaders,
      method: "POST",
    }),
    { params: Promise.resolve({ conversationId: "conv_route" }) },
  );
  assert.equal(partial.status, 500);
  assert.deepEqual(await partial.json(), { schema_version: 1, status: "partial" });

  for (const [code, expectedStatus, expectedState] of [
    ["bridge_unavailable", 503, "unavailable"],
    ["bridge_unsupported", 501, "unsupported"],
    ["conversation_conflict", 409, "conflict"],
    ["conversation_not_found", 404, "not_found"],
  ] as const) {
    const failed = await createConversationSteerHandler({
      gatewayPort: "8890",
      steer: async () => { throw new BridgeConversationsError(code); },
    })(
      new Request(`${origin}/api/conversations/conv_route/steer`, {
        body: '{"run_id":"run_route","text":"Use the exact route"}',
        headers: requestHeaders,
        method: "POST",
      }),
      { params: Promise.resolve({ conversationId: "conv_route" }) },
    );
    assert.equal(failed.status, expectedStatus, code);
    assert.deepEqual(await failed.json(), { schema_version: 1, status: expectedState });
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
