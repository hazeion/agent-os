import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeConversationsError,
  fetchBridgeConversationHistory,
  renameBridgeConversation,
  type PublicConversationHistory,
  type PublicConversationRenameResult,
} from "../src/lib/bridge-conversations.ts";
import { createConversationHistoryHandler } from "../src/lib/conversation-history-route.ts";
import { createConversationRenameHandler } from "../src/lib/conversation-rename-route.ts";
import { readConversationRenameBody } from "../src/lib/exact-json-body.ts";
import {
  fetchConversationHistory,
  PublicConversationError,
  renameConversation,
} from "../src/lib/public-conversations.ts";

const environment = {
  MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152",
  MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars",
};
const conversation = {
  agent_id: "agent_direct",
  archived_at: null,
  created_at: "2026-08-29T12:00:00Z",
  id: "conv_history",
  revision: 4,
  state: "active" as const,
  title: "Manual title",
  title_source: "manual" as const,
  updated_at: "2026-08-29T12:01:00Z",
};
const history: PublicConversationHistory = {
  conversations: [conversation],
  count: 1,
  next_cursor: "a".repeat(512),
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  status: "ready",
};
const renamed: PublicConversationRenameResult = {
  action: "rename",
  conversation,
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  status: "ready",
};

test("history bridge sends one fixed query and rejects widened projections", async () => {
  const calls: Array<{ body: BodyInit | null | undefined; method: string | undefined; url: string }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ body: init?.body, method: init?.method, url: input.toString() });
    return Response.json(history);
  };
  const result = await fetchBridgeConversationHistory("active", "Manual title", "cursor_1", fetcher, environment);
  assert.equal(result.conversations[0]?.title_source, "manual");
  assert.deepEqual(calls, [{
    body: undefined,
    method: "GET",
    url: "http://127.0.0.1:49152/bridge/v1/conversation-history?state=active&q=Manual+title&cursor=cursor_1",
  }]);

  for (const payload of [
    { ...history, message: "private" },
    { ...history, count: 2 },
    { ...history, conversations: [{ ...conversation, runtime_ref: "private" }] },
    { ...history, next_cursor: "x".repeat(513) },
  ]) {
    await assert.rejects(
      fetchBridgeConversationHistory("all", null, null, async () => Response.json(payload), environment),
      (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
    );
  }
  await assert.rejects(
    fetchBridgeConversationHistory("active", null, null, async () => Response.json({
      ...history,
      conversations: [{ ...conversation, state: "archived", archived_at: conversation.updated_at }],
    }), environment),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
  await assert.rejects(
    fetchBridgeConversationHistory("all", "bad\u200bquery", null, fetcher, environment),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "conversation_request_invalid",
  );
});

test("rename bridge binds exact Conversation, revision, title, and manual result", async () => {
  const calls: Array<{ body: BodyInit | null | undefined; url: string }> = [];
  const result = await renameBridgeConversation(
    conversation.id,
    3,
    conversation.title,
    async (input, init) => {
      calls.push({ body: init?.body, url: input.toString() });
      return Response.json(renamed);
    },
    environment,
  );
  assert.equal(result.conversation.title, "Manual title");
  assert.deepEqual(calls, [{
    body: '{"expected_revision":3,"title":"Manual title"}',
    url: "http://127.0.0.1:49152/bridge/v1/conversations/conv_history/rename",
  }]);
  await assert.rejects(
    renameBridgeConversation(conversation.id, 3, conversation.title, async () => Response.json({
      ...renamed,
      conversation: { ...conversation, id: "conv_other" },
    }), environment),
    (error: unknown) => error instanceof BridgeConversationsError && error.code === "bridge_response_invalid",
  );
});

test("history route requires exact state and leaves selection to the caller", async () => {
  const calls: unknown[][] = [];
  const handler = createConversationHistoryHandler({
    fetchHistory: async (...values) => { calls.push(values); return history; },
    gatewayPort: "8890",
  });
  const request = (query: string, origin = "http://127.0.0.1:8890") => new Request(`http://127.0.0.1:8890/api/conversation-history${query}`, {
    headers: { Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin" },
  });
  const response = await handler(request("?state=all&q=Manual+title&cursor=cursor_1"));
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [["all", "Manual title", "cursor_1"]]);
  assert.equal(response.headers.get("cache-control"), "private, no-store");

  for (const query of ["", "?state=recent", "?state=all&state=active", "?state=all&q=", "?state=all&extra=1"] ) {
    assert.equal((await handler(request(query))).status, 400, query);
  }
  assert.equal((await handler(request("?state=all", "https://attacker.example"))).status, 403);
  assert.equal(calls.length, 1);
});

test("rename body and route reject extra, padded, control, stale, and cross-origin input", async () => {
  const bodyRequest = (body: string) => new Request("http://127.0.0.1:8890/api/conversations/conv_history/rename", {
    body,
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  assert.deepEqual(await readConversationRenameBody(bodyRequest('{"expected_revision":3,"title":"Manual title"}')), {
    expectedRevision: 3,
    title: "Manual title",
  });
  for (const body of [
    '{"expected_revision":3,"title":" Manual title"}',
    '{"expected_revision":3,"title":"bad\\u0001title"}',
    '{"expected_revision":3,"title":"Manual title","extra":true}',
  ]) assert.equal(await readConversationRenameBody(bodyRequest(body)), null);

  const calls: unknown[][] = [];
  const handler = createConversationRenameHandler({
    gatewayPort: "8890",
    rename: async (...values) => { calls.push(values); return renamed; },
  });
  const routeRequest = (body: string, origin = "http://127.0.0.1:8890") => new Request("http://127.0.0.1:8890/api/conversations/conv_history/rename", {
    body,
    headers: { "Content-Type": "application/json", Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin" },
    method: "POST",
  });
  const response = await handler(routeRequest('{"expected_revision":3,"title":"Manual title"}'), {
    params: Promise.resolve({ conversationId: conversation.id }),
  });
  assert.equal(response.status, 200);
  assert.deepEqual(calls, [[conversation.id, 3, "Manual title"]]);
  const forbidden = await handler(routeRequest('{"expected_revision":3,"title":"Manual title"}', "https://attacker.example"), {
    params: Promise.resolve({ conversationId: conversation.id }),
  });
  assert.equal(forbidden.status, 403);
  assert.equal(calls.length, 1);

  const conflict = await createConversationRenameHandler({
    gatewayPort: "8890",
    rename: async () => { throw new BridgeConversationsError("conversation_conflict"); },
  })(routeRequest('{"expected_revision":3,"title":"Manual title"}'), {
    params: Promise.resolve({ conversationId: conversation.id }),
  });
  assert.equal(conflict.status, 409);
  assert.deepEqual(await conflict.json(), { schema_version: 1, status: "conflict" });
});

test("public history and rename clients build exact requests and revalidate replies", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ body: BodyInit | null | undefined; method: string | undefined; url: string }> = [];
  const responses: unknown[] = [history, renamed];
  globalThis.fetch = async (input, init) => {
    calls.push({ body: init?.body, method: init?.method, url: input.toString() });
    return Response.json(responses.shift());
  };
  try {
    assert.deepEqual(await fetchConversationHistory("all", "Manual title", "cursor_1"), history);
    assert.deepEqual(await renameConversation(conversation.id, 3, conversation.title), renamed);
    assert.deepEqual(calls, [
      {
        body: undefined,
        method: undefined,
        url: "/api/conversation-history?state=all&q=Manual+title&cursor=cursor_1",
      },
      {
        body: '{"expected_revision":3,"title":"Manual title"}',
        method: "POST",
        url: "/api/conversations/conv_history/rename",
      },
    ]);

    globalThis.fetch = async () => Response.json({ ...history, query: "private echo" });
    await assert.rejects(
      fetchConversationHistory("all"),
      (error: unknown) => error instanceof PublicConversationError && error.code === "response_invalid",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
