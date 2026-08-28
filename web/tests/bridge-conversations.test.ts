import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeConversationsError,
  CODEX_READINESS_BRIDGE_TIMEOUT_MILLISECONDS,
  CONVERSATION_TURN_BRIDGE_TIMEOUT_MILLISECONDS,
  cancelBridgeConversationTurn,
  archiveBridgeConversation,
  continueBridgeConversationTurn,
  createBridgeConversation,
  editBridgeConversationTurn,
  fetchBridgeActivity,
  fetchBridgeCodexReadiness,
  fetchBridgeConversation,
  fetchBridgeConversations,
  retryBridgeConversationRun,
  resumeBridgeConversationRun,
  steerBridgeConversation,
  submitBridgeConversationTurn,
} from "../src/lib/bridge-conversations.ts";
import {
  CODEX_READINESS_PUBLIC_TIMEOUT_MILLISECONDS,
  CONVERSATION_TURN_PUBLIC_TIMEOUT_MILLISECONDS,
  retryConversationRun,
} from "../src/lib/public-conversations.ts";

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
  queued_turns: [],
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
const message = {
  content: { parts: [{ text: "Start the work", type: "text" as const }], schema_version: 1 as const },
  conversation_id: conversation.id,
  created_at: "2026-08-25T12:01:00Z",
  id: "msg_abc123",
  revision: 1,
  role: "user" as const,
  run_id: "run_abc123",
  sequence: 1,
  state: "accepted" as const,
  updated_at: "2026-08-25T12:01:00Z",
};
const turnSubmission = {
  conversation: { ...conversation, revision: 2, title: "Start the work", title_source: "first_prompt" as const, updated_at: "2026-08-25T12:01:00Z" },
  disposition: "accepted" as const,
  duplicate: false,
  message,
  run: { id: "run_abc123", partial: false, status: "starting", updated_at: "2026-08-25T12:01:00Z" },
  runtime: "python" as const,
  schema_version: 1 as const,
  service: "mentat-local-bridge" as const,
  status: "ready" as const,
  turn: {
    attempt_count: 1 as const,
    blocked_reason: null,
    conversation_id: conversation.id,
    created_at: "2026-08-25T12:01:00Z",
    id: "turn_abc123",
    latest_run_id: "run_abc123",
    queue_ordinal: 1,
    revision: 3,
    state: "consumed" as const,
    updated_at: "2026-08-25T12:01:00Z",
    user_message_id: message.id,
  },
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

test("Conversation archive bridge is exact, reversible, and rejects cross-target results", async () => {
  const archived = {
    action: "archive" as const,
    conversation: {
      ...conversation,
      archived_at: "2026-08-25T12:02:00Z",
      revision: 2,
      state: "archived" as const,
      updated_at: "2026-08-25T12:02:00Z",
    },
    runtime: "python" as const,
    schema_version: 1 as const,
    service: "mentat-local-bridge" as const,
    status: "ready" as const,
  };
  const calls: Array<{ body: string | undefined; url: string }> = [];
  const result = await archiveBridgeConversation(
    conversation.id,
    conversation.revision,
    true,
    async (input, init) => {
      calls.push({ body: init?.body?.toString(), url: input.toString() });
      return Response.json(archived);
    },
    environment,
  );
  assert.equal(result.conversation.state, "archived");
  assert.deepEqual(calls, [{
    body: '{"expected_revision":1}',
    url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_abc123/archive",
  }]);
  await assert.rejects(
    archiveBridgeConversation(
      conversation.id,
      1,
      true,
      async () => Response.json({
        ...archived,
        conversation: { ...archived.conversation, id: "conv_cross_target" },
      }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError
      && error.code === "bridge_response_invalid",
  );
});

test("Conversation Retry bridge binds the exact source and idempotency key", async () => {
  const result = {
    action: "retry" as const,
    conversation_id: conversation.id,
    duplicate: false,
    run: { id: "run_retry", partial: false, status: "starting", updated_at: "2026-08-25T12:02:00Z" },
    runtime: "python" as const,
    schema_version: 1 as const,
    service: "mentat-local-bridge" as const,
    source_run_id: "run_abc123",
    status: "ready" as const,
  };
  const calls: Array<{ body: string | undefined; url: string }> = [];
  const retried = await retryBridgeConversationRun(
    conversation.id,
    "run_abc123",
    "conversation-retry-key",
    async (input, init) => {
      calls.push({ body: init?.body?.toString(), url: input.toString() });
      return Response.json(result, { status: 202 });
    },
    environment,
  );
  assert.equal(retried.run.id, "run_retry");
  assert.deepEqual(calls, [{
    body: '{"idempotency_key":"conversation-retry-key","source_run_id":"run_abc123"}',
    url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_abc123/retry",
  }]);
  const resumed = await resumeBridgeConversationRun(
    conversation.id,
    "run_abc123",
    "conversation-resume-key",
    async () => Response.json({ ...result, action: "resume", run: { ...result.run, id: "run_resume" } }, { status: 202 }),
    environment,
  );
  assert.equal(resumed.action, "resume");
  assert.equal(resumed.run.id, "run_resume");

  await assert.rejects(
    retryBridgeConversationRun(
      conversation.id,
      "run_abc123",
      "conversation-retry-key",
      async () => Response.json({ ...result, run: { ...result.run, id: "run_abc123" } }, { status: 202 }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError
      && error.code === "bridge_response_invalid",
  );

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => Response.json(
    { ...result, run: { ...result.run, id: "run_abc123" } },
    { status: 202 },
  );
  try {
    await assert.rejects(retryConversationRun(
      conversation.id,
      "run_abc123",
      "conversation-retry-key",
    ));
  } finally {
    globalThis.fetch = originalFetch;
  }
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

test("Conversation bridges allow only the exact public finalizing state", async () => {
  const currentRun = {
    id: "run_finalizing",
    partial: false,
    status: "finalizing",
    updated_at: "2026-08-25T12:02:00Z",
  };
  const projected = await fetchBridgeConversation(
    conversation.id,
    null,
    async () => Response.json({ ...detail, current_run: currentRun }),
    environment,
  );
  assert.equal(projected.current_run?.status, "finalizing");

  const activity = {
    activity: [{
      agent,
      attention: false,
      conversations: [{
        attention: false,
        id: conversation.id,
        run_id: currentRun.id,
        run_status: "finalizing",
        title: conversation.title,
        updated_at: currentRun.updated_at,
      }],
      state: "working",
      summary: "Run is finalizing",
      updated_at: currentRun.updated_at,
    }],
    direct_agent_id: agent.id,
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
  };
  const projectedActivity = await fetchBridgeActivity(
    async () => Response.json(activity),
    environment,
  );
  assert.equal(projectedActivity.activity[0].conversations[0].run_status, "finalizing");

  for (const invalidStatus of ["finalized", "artifact_pending"]) {
    await assert.rejects(
      fetchBridgeConversation(
        conversation.id,
        null,
        async () => Response.json({
          ...detail,
          current_run: { ...currentRun, status: invalidStatus },
        }),
        environment,
      ),
      (error: unknown) => error instanceof BridgeConversationsError
        && error.code === "bridge_response_invalid",
    );
  }
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

test("Conversation Turn bridge uses one exact named mutation and rejects private fields", async () => {
  const calls: Array<{ body: string | undefined; url: string }> = [];
  const submitted = await submitBridgeConversationTurn(
    conversation.id,
    "Start the work",
    "conversation-idempotency-key",
    async (input, init) => {
      calls.push({ body: init?.body?.toString(), url: input.toString() });
      return Response.json(turnSubmission, { status: 202 });
    },
    environment,
  );
  assert.equal(submitted.turn.id, "turn_abc123");
  assert.deepEqual(calls, [{
    body: '{"idempotency_key":"conversation-idempotency-key","text":"Start the work"}',
    url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_abc123/turns",
  }]);
  await assert.rejects(
    submitBridgeConversationTurn(
      conversation.id,
      "Start the work",
      "conversation-idempotency-key",
      async () => Response.json({ ...turnSubmission, execution_config_digest: "a".repeat(64) }, { status: 202 }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
});

test("Conversation Turn bridge maps admission and Codex setup states", async () => {
  await assert.rejects(
    submitBridgeConversationTurn(
      conversation.id,
      "Start the work",
      "conversation-idempotency-key",
      async () => Response.json({ runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "sign_in_required" }, { status: 409 }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "codex_sign_in_required",
  );
  const readiness = await fetchBridgeCodexReadiness(
    async () => Response.json({
      runtime: "python",
      schema_version: 1,
      service: "mentat-local-bridge",
      setup_command: "codex login",
      state: "sign_in_required",
      status: "ready",
    }),
    environment,
  );
  assert.equal(readiness.state, "sign_in_required");
  assert.equal(readiness.setup_command, "codex login");
  await assert.rejects(
    fetchBridgeCodexReadiness(
      async () => Response.json({ ...readiness, account_id: "private-account" }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
});

test("Conversation queue and steer bridges use exact named mutations", async () => {
  const queuedMessage = { ...message, revision: 2, run_id: null };
  const queuedTurn = {
    ...turnSubmission.turn,
    attempt_count: 0 as const,
    id: "turn_queue",
    latest_run_id: null,
    revision: 2,
    state: "pending" as const,
    user_message_id: queuedMessage.id,
  };
  const edited = {
    conversation: turnSubmission.conversation,
    disposition: "edited" as const,
    message: { ...queuedMessage, content: { parts: [{ text: "Edited follow-up", type: "text" as const }], schema_version: 1 as const } },
    runtime: "python" as const,
    schema_version: 1 as const,
    service: "mentat-local-bridge" as const,
    status: "ready" as const,
    turn: queuedTurn,
  };
  const cancelled = {
    ...edited,
    disposition: "cancelled" as const,
    message: { ...edited.message, state: "cancelled" as const },
    turn: { ...queuedTurn, state: "cancelled" as const },
  };
  const continued = {
    ...turnSubmission,
    message: { ...queuedMessage, run_id: "run_continue" },
    run: { id: "run_continue", partial: false, status: "starting", updated_at: "2026-08-25T12:01:00Z" },
    turn: {
      ...queuedTurn,
      attempt_count: 1 as const,
      latest_run_id: "run_continue",
      state: "consumed" as const,
    },
  };
  const steerResult = {
    action: "steer" as const,
    conversation_id: conversation.id,
    disposition: "accepted" as const,
    run_id: "run_abc123",
    runtime: "python" as const,
    schema_version: 1 as const,
    service: "mentat-local-bridge" as const,
    status: "ready" as const,
  };
  const calls: Array<{ body: string | undefined; url: string }> = [];
  const responses = [edited, cancelled, continued, steerResult];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ body: init?.body?.toString(), url: input.toString() });
    const response = responses.shift()!;
    return Response.json(response, { status: response === continued ? 202 : 200 });
  };

  await editBridgeConversationTurn(conversation.id, "turn_queue", 1, 2, "Edited follow-up", fetcher, environment);
  await cancelBridgeConversationTurn(conversation.id, "turn_queue", 2, 3, fetcher, environment);
  await continueBridgeConversationTurn(conversation.id, "turn_queue", 4, 5, fetcher, environment);
  await steerBridgeConversation(conversation.id, "run_abc123", "Use this guidance", fetcher, environment);

  assert.deepEqual(calls, [
    {
      body: '{"expected_message_revision":2,"expected_revision":1,"text":"Edited follow-up"}',
      url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_abc123/turns/turn_queue/edit",
    },
    {
      body: '{"expected_message_revision":3,"expected_revision":2}',
      url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_abc123/turns/turn_queue/cancel",
    },
    {
      body: '{"expected_message_revision":5,"expected_revision":4}',
      url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_abc123/turns/turn_queue/continue",
    },
    {
      body: '{"run_id":"run_abc123","text":"Use this guidance"}',
      url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_abc123/steer",
    },
  ]);

  await assert.rejects(
    editBridgeConversationTurn(
      conversation.id,
      "turn_queue",
      1,
      2,
      "Edited follow-up",
      async () => Response.json({ ...edited, runtime_run_ref: "private-canary" }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
  await assert.rejects(
    cancelBridgeConversationTurn(
      conversation.id,
      "turn_queue",
      2,
      3,
      async () => Response.json({
        ...cancelled,
        turn: { ...cancelled.turn, id: "turn_cross_target" },
      }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
  await assert.rejects(
    steerBridgeConversation(
      conversation.id,
      "run_abc123",
      "Use this guidance",
      async () => Response.json({ ...steerResult, run_id: "run_cross_target" }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
  await assert.rejects(
    steerBridgeConversation(
      conversation.id,
      "run_abc123",
      "Use this guidance",
      async () => Response.json({ runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "partial" }, { status: 500 }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "conversation_partial",
  );
});

test("Conversation mutation and readiness deadlines preserve outer response margins", async () => {
  assert.ok(
    CONVERSATION_TURN_BRIDGE_TIMEOUT_MILLISECONDS
    < CONVERSATION_TURN_PUBLIC_TIMEOUT_MILLISECONDS,
  );
  assert.ok(
    CODEX_READINESS_BRIDGE_TIMEOUT_MILLISECONDS
    < CODEX_READINESS_PUBLIC_TIMEOUT_MILLISECONDS,
  );

  const delayed = (delayMilliseconds: number, response: Response) =>
    async (_input: string | URL | Request, init?: RequestInit) =>
      await new Promise<Response>((resolve, reject) => {
        const timer = setTimeout(() => resolve(response), delayMilliseconds);
        const signal = init?.signal;
        const abort = () => {
          clearTimeout(timer);
          reject(signal?.reason ?? new Error("aborted"));
        };
        if (signal?.aborted) abort();
        else signal?.addEventListener("abort", abort, { once: true });
      });

  const accepted = await submitBridgeConversationTurn(
    conversation.id,
    "Start the work",
    "conversation-idempotency-key",
    delayed(5, Response.json(turnSubmission, { status: 202 })),
    environment,
    50,
  );
  assert.equal(accepted.run?.id, "run_abc123");
  await assert.rejects(
    submitBridgeConversationTurn(
      conversation.id,
      "Start the work",
      "conversation-idempotency-key",
      delayed(50, Response.json(turnSubmission, { status: 202 })),
      environment,
      10,
    ),
    (error: unknown) => error instanceof BridgeConversationsError
      && error.code === "bridge_unavailable",
  );

  const readinessPayload = {
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    setup_command: null,
    state: "ready",
    status: "ready",
  };
  const readiness = await fetchBridgeCodexReadiness(
    delayed(5, Response.json(readinessPayload)),
    environment,
    50,
  );
  assert.equal(readiness.state, "ready");
  await assert.rejects(
    fetchBridgeCodexReadiness(
      delayed(50, Response.json(readinessPayload)),
      environment,
      10,
    ),
    (error: unknown) => error instanceof BridgeConversationsError
      && error.code === "bridge_unavailable",
  );
});
