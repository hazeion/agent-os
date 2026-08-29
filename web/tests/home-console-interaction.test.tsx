import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { JSDOM } from "jsdom";

const origin = "http://127.0.0.1:8890";
const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  pretendToBeVisual: true,
  url: origin,
});
for (const name of [
  "document",
  "HTMLElement",
  "HTMLTextAreaElement",
  "KeyboardEvent",
  "MouseEvent",
  "MutationObserver",
  "Node",
  "navigator",
  "window",
] as const) {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    value: dom.window[name],
  });
}
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", {
  configurable: true,
  value: true,
  writable: true,
});
globalThis.requestAnimationFrame = (callback) => setTimeout(callback, 0);
globalThis.cancelAnimationFrame = (handle) => clearTimeout(handle);

const { act, cleanup, fireEvent, render, screen, waitFor } = await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { HomeConsole } = await import("../src/app/home-console.tsx");
const { transcriptContentLimits } = await import("../src/app/transcript-content.tsx");
const originalEventSource = globalThis.EventSource;

const timestamp = "2026-08-26T12:00:00Z";
const agent = {
  capabilities: ["run.message", "run.start"],
  id: "agent_direct",
  name: "Direct Agent",
  runtime_type: "codex",
  system_role: "direct",
};
const conversation = {
  agent_id: agent.id,
  archived_at: null,
  created_at: timestamp,
  id: "conv_ui",
  revision: 1,
  state: "active",
  title: "New conversation",
  title_source: "default",
  updated_at: timestamp,
};
type ConversationFixture = Omit<typeof conversation, "archived_at" | "state"> & {
  archived_at: string | null;
  state: "active" | "archived";
};
const list = {
  agents: [agent],
  conversations: [conversation],
  count: 1,
  direct_agent_id: agent.id,
  next_cursor: null,
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  status: "ready",
};
const activity = {
  activity: [],
  direct_agent_id: null,
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  status: "ready",
};

function detail(
  currentRun: null | Record<string, unknown> = null,
  targetConversation: Record<string, unknown> = conversation,
  queuedTurns: Array<Record<string, unknown>> = [],
  messages: Array<Record<string, unknown>> = [],
  targetAgent = agent,
) {
  return {
    agent: targetAgent,
    conversation: targetConversation,
    current_run: currentRun,
    messages,
    next_message_cursor: null,
    queued_turns: queuedTurns,
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
  };
}

function queuedFixture(
  state: "pending" | "blocked" = "pending",
  blockedReason: "failed" | null = state === "blocked" ? "failed" : null,
) {
  const queuedMessage = {
    content: { parts: [{ text: "Queued follow-up", type: "text" }], schema_version: 1 },
    conversation_id: conversation.id,
    created_at: timestamp,
    id: "msg_queue",
    revision: 2,
    role: "user",
    run_id: null,
    sequence: 2,
    state: "accepted",
    updated_at: timestamp,
  };
  const queuedTurn = {
    blocked_reason: blockedReason,
    conversation_id: conversation.id,
    created_at: timestamp,
    id: "turn_queue",
    message_revision: queuedMessage.revision,
    queue_ordinal: 2,
    revision: 3,
    state,
    text: queuedMessage.content.parts[0].text,
    updated_at: timestamp,
    user_message_id: queuedMessage.id,
  };
  return { queuedMessage, queuedTurn };
}

function secondQueuedFixture(
  state: "pending" | "blocked" = "pending",
  blockedReason: "failed" | null = state === "blocked" ? "failed" : null,
) {
  const fixture = queuedFixture(state, blockedReason);
  const queuedMessage = {
    ...fixture.queuedMessage,
    content: { parts: [{ text: "Second queued follow-up", type: "text" }], schema_version: 1 },
    id: "msg_queue_second",
    sequence: 3,
  };
  return {
    queuedMessage,
    queuedTurn: {
      ...fixture.queuedTurn,
      id: "turn_queue_second",
      queue_ordinal: 3,
      text: queuedMessage.content.parts[0].text,
      user_message_id: queuedMessage.id,
    },
  };
}

function pendingSubmission(text: string) {
  const fixture = queuedFixture();
  const updatedMessage = {
    ...fixture.queuedMessage,
    content: { parts: [{ text, type: "text" }], schema_version: 1 },
    revision: 1,
  };
  return {
    conversation: { ...conversation, revision: 2, title: text, title_source: "first_prompt" },
    disposition: "pending",
    duplicate: false,
    message: updatedMessage,
    run: null,
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
    turn: {
      attempt_count: 0,
      blocked_reason: null,
      conversation_id: conversation.id,
      created_at: timestamp,
      id: fixture.queuedTurn.id,
      latest_run_id: null,
      queue_ordinal: fixture.queuedTurn.queue_ordinal,
      revision: 1,
      state: "pending",
      updated_at: timestamp,
      user_message_id: updatedMessage.id,
    },
  };
}

function queueMutation(
  disposition: "edited" | "cancelled",
  text: string,
  turnRevision: number,
  messageRevision: number,
) {
  const fixture = queuedFixture();
  const cancelled = disposition === "cancelled";
  return {
    conversation: { ...conversation, revision: conversation.revision + turnRevision },
    disposition,
    message: {
      ...fixture.queuedMessage,
      content: { parts: [{ text, type: "text" }], schema_version: 1 },
      revision: messageRevision,
      state: cancelled ? "cancelled" : "accepted",
    },
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
    turn: {
      attempt_count: 0,
      blocked_reason: null,
      conversation_id: conversation.id,
      created_at: timestamp,
      id: fixture.queuedTurn.id,
      latest_run_id: null,
      queue_ordinal: fixture.queuedTurn.queue_ordinal,
      revision: turnRevision,
      state: cancelled ? "cancelled" : "pending",
      updated_at: timestamp,
      user_message_id: fixture.queuedMessage.id,
    },
  };
}

function acceptedQueuedSubmission(text: string) {
  const fixture = queuedFixture("blocked");
  const runId = "run_continue";
  return {
    conversation: { ...conversation, revision: 2 },
    disposition: "accepted",
    duplicate: false,
    message: {
      ...fixture.queuedMessage,
      content: { parts: [{ text, type: "text" }], schema_version: 1 },
      revision: 3,
      run_id: runId,
    },
    run: { id: runId, partial: false, status: "starting", updated_at: timestamp },
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
    turn: {
      attempt_count: 1,
      blocked_reason: null,
      conversation_id: conversation.id,
      created_at: timestamp,
      id: fixture.queuedTurn.id,
      latest_run_id: runId,
      queue_ordinal: fixture.queuedTurn.queue_ordinal,
      revision: 4,
      state: "consumed",
      updated_at: timestamp,
      user_message_id: fixture.queuedMessage.id,
    },
  };
}

function transcriptMessage(
  sequence: number,
  role: "assistant" | "user",
  text: string,
  runId: string | null = null,
) {
  return {
    content: { parts: [{ text, type: "text" }], schema_version: 1 },
    conversation_id: conversation.id,
    created_at: timestamp,
    id: `msg_transcript_${sequence}`,
    revision: 1,
    role,
    run_id: runId,
    sequence,
    state: "accepted",
    updated_at: timestamp,
  };
}

class MockEventSource {
  static instances: MockEventSource[] = [];

  readonly url: string;
  readonly listeners = new Map<string, Set<EventListenerOrEventListenerObject>>();
  closed = false;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string | URL) {
    this.url = url.toString();
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
    if (!listener) return;
    const listeners = this.listeners.get(type) ?? new Set<EventListenerOrEventListenerObject>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
    if (listener) this.listeners.get(type)?.delete(listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: string) {
    const event = new dom.window.MessageEvent(type, { data }) as unknown as Event;
    for (const listener of this.listeners.get(type) ?? []) {
      if (typeof listener === "function") listener(event);
      else listener.handleEvent(event);
    }
  }
}

function acceptedSubmission(text: string, targetConversation = conversation) {
  const runId = `run_${targetConversation.id}`;
  const updatedConversation = {
    ...targetConversation,
    revision: targetConversation.revision + 1,
    title: text,
    title_source: "first_prompt",
  };
  const message = {
    content: { parts: [{ text, type: "text" }], schema_version: 1 },
    conversation_id: targetConversation.id,
    created_at: timestamp,
    id: `msg_${targetConversation.id}`,
    revision: 1,
    role: "user",
    run_id: runId,
    sequence: 1,
    state: "accepted",
    updated_at: timestamp,
  };
  return {
    conversation: updatedConversation,
    disposition: "accepted",
    duplicate: false,
    message,
    run: { id: runId, partial: false, status: "starting", updated_at: timestamp },
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
    turn: {
      attempt_count: 1,
      blocked_reason: null,
      conversation_id: targetConversation.id,
      created_at: timestamp,
      id: `turn_${targetConversation.id}`,
      latest_run_id: runId,
      queue_ordinal: 1,
      revision: 3,
      state: "consumed",
      updated_at: timestamp,
      user_message_id: `msg_${targetConversation.id}`,
    },
  };
}

function pathOf(input: string | URL | Request): string {
  return new URL(input instanceof Request ? input.url : input.toString(), origin).pathname;
}

function deferredResponse() {
  let resolve: ((response: Response) => void) | undefined;
  const promise = new Promise<Response>((next) => { resolve = next; });
  return {
    promise,
    resolve(response: Response) {
      assert.ok(resolve);
      resolve(response);
    },
  };
}

function installFetch({
  currentRun = null,
  currentRunAfterTurn = currentRun,
  conversationList = list,
  readinessState = "ready",
  turnResponse,
}: Readonly<{
  currentRun?: null | Record<string, unknown>;
  currentRunAfterTurn?: null | Record<string, unknown>;
  conversationList?: typeof list;
  readinessState?: "cli_missing" | "sign_in_required" | "ready" | "unavailable";
  turnResponse?: () => Promise<Response>;
}> = {}) {
  const calls: Array<{ body: string | undefined; method: string; path: string }> = [];
  let turnRequested = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    calls.push({ body: init?.body?.toString(), method, path });
    if (path === "/api/conversations" && method === "GET") return Response.json(conversationList);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === "/api/conversations/conv_ui" && method === "GET") {
      return Response.json(detail(turnRequested ? currentRunAfterTurn : currentRun));
    }
    if (path === "/api/conversations/conv_ui/turns" && method === "POST" && turnResponse) {
      turnRequested = true;
      return await turnResponse();
    }
    if (path === "/api/codex-readiness" && method === "GET") {
      return Response.json({
        runtime: "python",
        schema_version: 1,
        service: "mentat-local-bridge",
        setup_command: readinessState === "sign_in_required" ? "codex login" : null,
        state: readinessState,
        status: "ready",
      });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  return calls;
}

afterEach(() => {
  cleanup();
  if (originalEventSource === undefined) {
    delete (globalThis as { EventSource?: typeof EventSource }).EventSource;
  } else {
    Object.defineProperty(globalThis, "EventSource", { configurable: true, value: originalEventSource });
  }
});

test("Home Console does not invent an active-Run block for an empty workspace", async () => {
  installFetch({
    conversationList: { ...list, conversations: [], count: 0 },
  });
  render(<HomeConsole />);

  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await waitFor(() => assert.equal(prompt.placeholder, "Write a prompt for your Agent…"));
  assert.equal(prompt.disabled, false);
  assert.equal((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled, true);
  assert.doesNotMatch(document.body.textContent ?? "", /Refreshing the active Run/u);
});

test("Home Console enables Send and normalizes an accidental trailing space", async () => {
  const calls = installFetch({
    turnResponse: async () => Response.json(acceptedSubmission("Ready to send"), { status: 202 }),
  });
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);

  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await user.click(screen.getByRole("button", { name: "Check readiness" }));
  await waitFor(() => assert.equal(screen.getByRole("status").textContent, "Codex is signed in and ready."));
  await user.type(prompt, "Ready to send ");

  const send = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
  assert.equal(send.disabled, false);
  await user.click(send);
  await waitFor(() => assert.equal(prompt.value, ""));

  const turnBody = JSON.parse(calls.find((call) => call.path.endsWith("/turns"))?.body ?? "{}");
  assert.equal(turnBody.text, "Ready to send");
});

test("Home Console gates initial drafting and moves an unbound draft only once", async () => {
  let resolveList: ((response: Response) => void) | undefined;
  const listResponse = new Promise<Response>((resolve) => { resolveList = resolve; });
  let creationCount = 0;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return await listResponse;
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === "/api/conversations" && method === "POST") {
      creationCount += 1;
      const created = {
        ...conversation,
        id: `conv_created_${creationCount}`,
      };
      return Response.json(detail(null, created), { status: 201 });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const prompt = screen.getByLabelText("Prompt") as HTMLTextAreaElement;
  assert.equal(prompt.disabled, true);
  assert.equal(prompt.placeholder, "Loading Conversations");

  await act(async () => {
    resolveList?.(Response.json({ ...list, conversations: [], count: 0 }));
    await listResponse;
  });
  await waitFor(() => assert.equal(prompt.disabled, false));
  await user.type(prompt, "Carry once");
  await user.click(screen.getByRole("button", { name: "New conversation" }));
  await waitFor(() => assert.equal(prompt.value, "Carry once"));

  await user.click(screen.getByRole("button", { name: "New conversation" }));
  await waitFor(() => assert.equal(prompt.value, ""));
  assert.equal(creationCount, 2);
});

test("Home Console executes Shift+Enter, IME, optimistic paint, and pre-admission rollback", async () => {
  let resolveTurn: ((response: Response) => void) | undefined;
  const deferredTurn = new Promise<Response>((resolve) => { resolveTurn = resolve; });
  const calls = installFetch({
    currentRunAfterTurn: {
      id: "run_conflict",
      partial: false,
      status: "running",
      updated_at: timestamp,
    },
    turnResponse: async () => await deferredTurn,
  });
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);

  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await waitFor(() => assert.equal(prompt.disabled, false));
  assert.equal((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled, true);
  await user.click(screen.getByRole("button", { name: "Check readiness" }));
  await waitFor(() => assert.equal(screen.getByRole("status").textContent, "Codex is signed in and ready."));

  await user.type(prompt, "First line");
  await user.keyboard("{Shift>}{Enter}{/Shift}Second line");
  assert.equal(prompt.value, "First line\nSecond line");
  assert.equal(calls.filter((call) => call.path.endsWith("/turns")).length, 0);

  fireEvent.compositionStart(prompt);
  fireEvent.keyDown(prompt, { code: "Enter", isComposing: false, key: "Enter", keyCode: 13 });
  fireEvent.compositionEnd(prompt);
  fireEvent.keyDown(prompt, { code: "Enter", isComposing: false, key: "Enter", keyCode: 229 });
  assert.equal(calls.filter((call) => call.path.endsWith("/turns")).length, 0);

  fireEvent.keyDown(prompt, { code: "Enter", key: "Enter", keyCode: 13 });
  await screen.findByLabelText("Sending message");
  assert.equal(prompt.disabled, true);
  assert.equal(screen.getByRole("status").textContent, "Submitting the exact Turn…");
  assert.equal(calls.filter((call) => call.path.endsWith("/turns")).length, 1);
  fireEvent.change(prompt, { target: { value: "Changed while disabled" } });

  await act(async () => {
    resolveTurn?.(Response.json({ schema_version: 1, status: "active_run" }, { status: 409 }));
    await deferredTurn;
  });
  await waitFor(() => assert.equal(screen.queryByLabelText("Sending message"), null));
  assert.equal(prompt.value, "First line\nSecond line");
  assert.equal(prompt.disabled, false);
  assert.equal(prompt.placeholder, "Write a follow-up to queue, or begin with /steer");
  assert.equal(
    screen.getByRole("status").textContent,
    "The Run changed during admission. The draft was kept; refresh completed before another Send.",
  );
});

test("Home Console reuses the exact key only for the unchanged ambiguous draft", async () => {
  let attempts = 0;
  const calls = installFetch({
    turnResponse: async () => {
      attempts += 1;
      return attempts === 1
        ? Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 })
        : Response.json(acceptedSubmission("Retry exactly"), { status: 202 });
    },
  });
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await user.click(screen.getByRole("button", { name: "Check readiness" }));
  await waitFor(() => assert.equal(screen.getByRole("status").textContent, "Codex is signed in and ready."));
  await user.type(prompt, "Retry exactly");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /exact retry key were kept/u));
  assert.equal(prompt.value, "Retry exactly");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => assert.equal(screen.getByRole("status").textContent, "Turn accepted. The Run is now visible in this Conversation."));

  const turnBodies = calls
    .filter((call) => call.path.endsWith("/turns"))
    .map((call) => JSON.parse(call.body ?? "{}") as Record<string, unknown>);
  assert.equal(turnBodies.length, 2);
  assert.equal(turnBodies[0].idempotency_key, turnBodies[1].idempotency_key);
  assert.equal(turnBodies[0].text, "Retry exactly");
  assert.equal(prompt.value, "");
});

test("Home Console scopes in-flight drafts and exact retry keys per Conversation", async () => {
  const otherConversation = {
    ...conversation,
    id: "conv_other",
    title: "Other conversation",
    title_source: "first_prompt",
  };
  const conversationList = {
    ...list,
    conversations: [conversation, otherConversation],
    count: 2,
  };
  const activityWithConversation = {
    ...activity,
    direct_agent_id: agent.id,
    activity: [{
      agent,
      attention: true,
      conversations: [{
        attention: true,
        id: conversation.id,
        run_id: "run_activity",
        run_status: "unknown",
        title: "Conversation A",
        updated_at: timestamp,
      }],
      state: "waiting",
      summary: "Waiting for an exact retry",
      updated_at: timestamp,
    }],
  };
  let resolveFirst: ((response: Response) => void) | undefined;
  const firstResponse = new Promise<Response>((resolve) => { resolveFirst = resolve; });
  const turnBodies = new Map<string, Array<Record<string, unknown>>>();
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(conversationList);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activityWithConversation);
    if (path === "/api/codex-readiness" && method === "GET") {
      return Response.json({
        runtime: "python",
        schema_version: 1,
        service: "mentat-local-bridge",
        setup_command: null,
        state: "ready",
        status: "ready",
      });
    }
    const detailMatch = /^\/api\/conversations\/(conv_[^/]+)$/u.exec(path);
    if (detailMatch && method === "GET") {
      const target = detailMatch[1] === otherConversation.id
        ? otherConversation
        : conversation;
      return Response.json(detail(null, target));
    }
    const turnMatch = /^\/api\/conversations\/(conv_[^/]+)\/turns$/u.exec(path);
    if (turnMatch && method === "POST") {
      const conversationId = turnMatch[1];
      const body = JSON.parse(init?.body?.toString() ?? "{}") as Record<string, unknown>;
      const bodies = turnBodies.get(conversationId) ?? [];
      bodies.push(body);
      turnBodies.set(conversationId, bodies);
      if (conversationId === conversation.id && bodies.length === 1) {
        return await firstResponse;
      }
      const target = conversationId === otherConversation.id
        ? otherConversation
        : conversation;
      return Response.json(acceptedSubmission(String(body.text), target), { status: 202 });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await user.click(screen.getByRole("button", { name: "Check readiness" }));
  await waitFor(() => assert.equal(screen.getByRole("status").textContent, "Codex is signed in and ready."));

  await user.type(prompt, "Retry A");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByLabelText("Sending message");
  fireEvent.click(document.getElementById(`conversation-tab-${otherConversation.id}`)!);
  await waitFor(() => {
    assert.equal(prompt.value, "");
    assert.equal(prompt.disabled, false);
    assert.equal(screen.queryByLabelText("Sending message"), null);
  });
  await user.type(prompt, "Draft B");

  await act(async () => {
    resolveFirst?.(Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 }));
    await firstResponse;
  });
  await waitFor(() => assert.doesNotMatch(screen.getByRole("status").textContent ?? "", /exact retry key were kept/u));
  assert.equal(prompt.value, "Draft B");

  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => assert.equal(prompt.value, ""));
  fireEvent.click(document.querySelector<HTMLButtonElement>(".activity-agent-toggle")!);
  fireEvent.click(document.querySelector<HTMLButtonElement>(`#activity-agent-${agent.id} li button`)!);
  await waitFor(() => {
    assert.equal(prompt.value, "Retry A");
    assert.match(screen.getByRole("status").textContent ?? "", /exact retry key were kept/u);
  });
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => assert.equal(prompt.value, ""));

  const aBodies = turnBodies.get(conversation.id) ?? [];
  const bBodies = turnBodies.get(otherConversation.id) ?? [];
  assert.equal(aBodies.length, 2);
  assert.equal(bBodies.length, 1);
  assert.equal(aBodies[0].idempotency_key, aBodies[1].idempotency_key);
  assert.notEqual(aBodies[0].idempotency_key, bBodies[0].idempotency_key);

  await user.click(screen.getByRole("button", { name: "New conversation" }));
  await waitFor(() => assert.equal(
    screen.getByRole("status").textContent,
    "Mentat could not create that Conversation. Try again.",
  ));
});

test("Home Console keeps composing writable for an active Run", async () => {
  installFetch({
    currentRun: {
      id: "run_active",
      partial: false,
      status: "running",
      updated_at: timestamp,
    },
  });
  render(<HomeConsole />);
  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await waitFor(() => {
    assert.equal(prompt.disabled, false);
    assert.equal(prompt.placeholder, "Write a follow-up to queue, or begin with /steer");
  });
  assert.equal((screen.getByRole("button", { name: "Queue" }) as HTMLButtonElement).disabled, true);
});

test("Home Console keeps the exact stream and queue affordance while Hermes finalizes", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", {
    configurable: true,
    value: MockEventSource,
  });
  const finalizingRun = {
    id: "run_finalizing",
    partial: false,
    status: "finalizing",
    updated_at: timestamp,
  };
  installFetch({ currentRun: finalizingRun });

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));

  assert.equal(
    MockEventSource.instances[0].url,
    `/api/runs/${finalizingRun.id}/events`,
  );
  assert.match(document.querySelector(".selected-run-progress")?.textContent ?? "", /Run Reconciling/u);
  await act(async () => {
    MockEventSource.instances[0].emit("snapshot", JSON.stringify({
      event: { run_id: finalizingRun.id, summary: "Final evidence is durable" },
    }));
  });
  await waitFor(() => assert.match(
    document.querySelector(".selected-run-progress")?.textContent ?? "",
    /Run Finalizing/u,
  ));
  assert.equal(prompt.placeholder, "Write a follow-up to queue, or begin with /steer");
  await user.type(prompt, "Queue after final artifacts are durable");
  assert.equal((screen.getByRole("button", { name: "Queue" }) as HTMLButtonElement).disabled, false);
});

test("Home Console durably queues an ordinary Send behind the active Run", async () => {
  const activeRun = {
    id: "run_active",
    partial: false,
    status: "running",
    updated_at: timestamp,
  };
  const text = "Queue this follow-up";
  const submitted = pendingSubmission(text);
  const queuedTurn = {
    ...queuedFixture().queuedTurn,
    message_revision: submitted.message.revision,
    revision: submitted.turn.revision,
    text,
  };
  const calls: Array<{ body: string | undefined; method: string; path: string }> = [];
  let admitted = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    calls.push({ body: init?.body?.toString(), method, path });
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(admitted
        ? detail(activeRun, submitted.conversation, [queuedTurn], [submitted.message])
        : detail(activeRun));
    }
    if (path === `/api/conversations/${conversation.id}/turns` && method === "POST") {
      admitted = true;
      return Response.json(submitted);
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await waitFor(() => assert.equal(prompt.placeholder, "Write a follow-up to queue, or begin with /steer"));
  await user.type(prompt, text);
  const dispatchStartedAt = performance.now();
  await user.click(screen.getByRole("button", { name: "Queue" }));

  await waitFor(() => assert.equal(prompt.value, ""), { timeout: 1_000 });
  assert.ok(performance.now() - dispatchStartedAt < 1_000);
  assert.equal(screen.getByRole("status").textContent, "Turn queued behind the current work.");
  assert.match(screen.getByLabelText("Queued Turns").textContent ?? "", /1 \/ 8 waiting/u);
  assert.match(screen.getByLabelText("Queued Turns").textContent ?? "", new RegExp(text, "u"));
  const turnCall = calls.find((call) => call.path.endsWith("/turns") && call.method === "POST");
  assert.ok(turnCall);
  const body = JSON.parse(turnCall.body ?? "{}") as Record<string, unknown>;
  assert.deepEqual(Object.keys(body).sort(), ["idempotency_key", "text"]);
  assert.equal(body.text, text);
});

test("Home Console keeps a ninth active-queue Turn client-side", async () => {
  const currentRun = {
    id: "run_queue_capacity",
    partial: false,
    status: "running",
    updated_at: timestamp,
  };
  const messages = Array.from({ length: 8 }, (_, index) => ({
    ...transcriptMessage(index + 1, "user", `Queued capacity ${index + 1}`),
    id: `msg_queue_capacity_${index + 1}`,
  }));
  const turns = messages.map((message, index) => ({
    blocked_reason: null,
    conversation_id: conversation.id,
    created_at: timestamp,
    id: `turn_queue_capacity_${index + 1}`,
    message_revision: message.revision,
    queue_ordinal: index + 2,
    revision: 1,
    state: "pending",
    text: message.content.parts[0].text,
    updated_at: timestamp,
    user_message_id: message.id,
  }));
  const calls: string[] = [];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    calls.push(`${method} ${path}`);
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(currentRun, conversation, turns, messages));
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await waitFor(() => assert.match(screen.getByLabelText("Queued Turns").textContent ?? "", /8 \/ 8 waiting/u));
  const editButtons = screen.getAllByRole("button", { name: /Edit queued Turn/u });
  const cancelButtons = screen.getAllByRole("button", { name: /Cancel queued Turn/u });
  assert.equal(editButtons.length, 8);
  assert.equal(cancelButtons.length, 8);
  assert.equal(new Set(editButtons.map((button) => button.getAttribute("aria-label"))).size, 8);
  assert.equal(new Set(cancelButtons.map((button) => button.getAttribute("aria-label"))).size, 8);
  await user.type(prompt, "This ninth Turn must stay here");
  assert.equal((screen.getByRole("button", { name: "Queue" }) as HTMLButtonElement).disabled, true);
  assert.match(document.querySelector(".composer-boundary")?.textContent ?? "", /Queue full/u);
  assert.equal(calls.some((call) => call.includes("POST") && call.endsWith("/turns")), false);
});

test("Home Console edits and cancels a queued Turn with both exact revisions", async () => {
  const fixture = queuedFixture();
  const editedText = "Edited queued follow-up";
  const edited = queueMutation("edited", editedText, 4, 3);
  const cancelled = queueMutation("cancelled", editedText, 5, 4);
  const mutationCalls: Array<{ body: Record<string, unknown>; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(null, conversation, [fixture.queuedTurn], [fixture.queuedMessage]));
    }
    if (method === "POST" && (path.endsWith("/edit") || path.endsWith("/cancel"))) {
      mutationCalls.push({
        body: JSON.parse(init?.body?.toString() ?? "{}") as Record<string, unknown>,
        path,
      });
      return Response.json(path.endsWith("/edit") ? edited : cancelled);
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await screen.findByLabelText("Queued Turns");
  await user.click(screen.getByRole("button", { name: "Edit queued Turn 2" }));
  const editBox = screen.getByLabelText("Edit queued Turn 2") as HTMLTextAreaElement;
  assert.equal(document.activeElement, editBox);
  await user.clear(editBox);
  await user.type(editBox, editedText);
  await user.click(screen.getByRole("button", { name: "Save queued Turn 2" }));
  await waitFor(() => assert.equal(
    screen.getByRole("status").textContent,
    "Queued Turn #2 was updated.",
  ));
  await waitFor(() => assert.equal(
    document.activeElement,
    screen.getByRole("button", { name: "Edit queued Turn 2" }),
  ));
  assert.match(screen.getByLabelText("Queued Turns").textContent ?? "", new RegExp(editedText, "u"));

  await user.click(screen.getByRole("button", { name: "Cancel queued Turn 2" }));
  await waitFor(() => assert.equal(screen.queryByLabelText("Queued Turns"), null));
  await waitFor(() => assert.equal(document.activeElement, screen.getByLabelText("Prompt")));
  assert.equal(screen.getByRole("status").textContent, "Queued Turn #2 was cancelled. Its FIFO ordinal remains retired.");
  assert.equal(document.querySelector(".message-cancelled .transcript-markdown")?.textContent, editedText);
  assert.deepEqual(mutationCalls, [
    {
      body: { expected_message_revision: 2, expected_revision: 3, text: editedText },
      path: `/api/conversations/${conversation.id}/turns/${fixture.queuedTurn.id}/edit`,
    },
    {
      body: { expected_message_revision: 3, expected_revision: 4 },
      path: `/api/conversations/${conversation.id}/turns/${fixture.queuedTurn.id}/cancel`,
    },
  ]);
});

test("Home Console gives multi-row queue actions unique names and restores keyboard focus", async () => {
  const first = queuedFixture();
  const secondMessage = {
    ...first.queuedMessage,
    content: { parts: [{ text: "Second queued follow-up", type: "text" }], schema_version: 1 },
    id: "msg_queue_second",
    sequence: 3,
  };
  const secondTurn = {
    ...first.queuedTurn,
    id: "turn_queue_second",
    queue_ordinal: 3,
    text: secondMessage.content.parts[0].text,
    user_message_id: secondMessage.id,
  };
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(
        null,
        conversation,
        [first.queuedTurn, secondTurn],
        [first.queuedMessage, secondMessage],
      ));
    }
    if (path.endsWith(`/${first.queuedTurn.id}/cancel`) && method === "POST") {
      return Response.json(queueMutation("cancelled", first.queuedTurn.text, 4, 3));
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await screen.findByRole("button", { name: "Edit queued Turn 2" });
  assert.ok(screen.getByRole("button", { name: "Edit queued Turn 3" }));
  assert.ok(screen.getByRole("button", { name: "Cancel queued Turn 2" }));
  assert.ok(screen.getByRole("button", { name: "Cancel queued Turn 3" }));

  await user.click(screen.getByRole("button", { name: "Edit queued Turn 3" }));
  await user.click(screen.getByRole("button", { name: "Discard queued Turn 3 edit" }));
  await waitFor(() => assert.equal(
    document.activeElement,
    screen.getByRole("button", { name: "Edit queued Turn 3" }),
  ));

  const cancelFirst = screen.getByRole("button", { name: "Cancel queued Turn 2" });
  cancelFirst.focus();
  await user.keyboard("{Enter}");
  await waitFor(() => assert.equal(screen.queryByRole("button", { name: "Cancel queued Turn 2" }), null));
  await waitFor(() => assert.equal(
    document.activeElement,
    screen.getByRole("button", { name: "Edit queued Turn 3" }),
  ));
});

test("Home Console keeps a delayed queue mutation scoped away from another tab's editor", async () => {
  const first = queuedFixture();
  const otherConversation = {
    ...conversation,
    id: "conv_queue_other",
    title: "Other queue",
    title_source: "first_prompt",
  };
  const otherMessage = {
    ...first.queuedMessage,
    content: { parts: [{ text: "Other queued follow-up", type: "text" }], schema_version: 1 },
    conversation_id: otherConversation.id,
    id: "msg_queue_other",
  };
  const otherTurn = {
    ...first.queuedTurn,
    conversation_id: otherConversation.id,
    id: "turn_queue_other",
    text: otherMessage.content.parts[0].text,
    user_message_id: otherMessage.id,
  };
  const editedText = "Edited in the first tab";
  const editResponse = deferredResponse();
  let editRequested = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") {
      return Response.json({ ...list, conversations: [conversation, otherConversation], count: 2 });
    }
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(null, conversation, [first.queuedTurn], [first.queuedMessage]));
    }
    if (path === `/api/conversations/${otherConversation.id}` && method === "GET") {
      return Response.json(detail(null, otherConversation, [otherTurn], [otherMessage]));
    }
    if (path.endsWith(`/${first.queuedTurn.id}/edit`) && method === "POST") {
      editRequested = true;
      return await editResponse.promise;
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await screen.findByRole("button", { name: "Edit queued Turn 2" });
  await user.click(screen.getByRole("button", { name: "Edit queued Turn 2" }));
  const firstEditor = screen.getByLabelText("Edit queued Turn 2") as HTMLTextAreaElement;
  await user.clear(firstEditor);
  await user.type(firstEditor, editedText);
  await user.click(screen.getByRole("button", { name: "Save queued Turn 2" }));
  await waitFor(() => assert.equal(editRequested, true));

  fireEvent.click(document.getElementById(`conversation-tab-${otherConversation.id}`)!);
  const otherEditButton = await screen.findByRole("button", { name: "Edit queued Turn 2" });
  await user.click(otherEditButton);
  const otherEditor = screen.getByLabelText("Edit queued Turn 2") as HTMLTextAreaElement;
  await user.clear(otherEditor);
  await user.type(otherEditor, "Other editor remains open");
  assert.equal(document.activeElement, otherEditor);

  editResponse.resolve(Response.json(queueMutation("edited", editedText, 4, 3)));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  assert.equal(document.activeElement, otherEditor);
  assert.equal(otherEditor.value, "Other editor remains open");
  assert.doesNotMatch(screen.getByRole("status").textContent ?? "", /was updated/u);

  fireEvent.click(document.getElementById(`conversation-tab-${conversation.id}`)!);
  await waitFor(() => assert.match(
    screen.getByLabelText("Queued Turns").textContent ?? "",
    new RegExp(editedText, "u"),
  ));
  assert.equal(screen.getByRole("status").textContent, "Queued Turn #2 was updated.");
  fireEvent.click(document.getElementById(`conversation-tab-${otherConversation.id}`)!);
  const restoredOtherEditor = await screen.findByLabelText("Edit queued Turn 2") as HTMLTextAreaElement;
  assert.equal(restoredOtherEditor.value, "Other editor remains open");
});

test("Home Console does not let a delayed edit steal focus from a newer Turn editor", async () => {
  const first = queuedFixture();
  const second = secondQueuedFixture();
  const editedText = "Edited first queued follow-up";
  const editResponse = deferredResponse();
  let editRequested = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(
        null,
        conversation,
        [first.queuedTurn, second.queuedTurn],
        [first.queuedMessage, second.queuedMessage],
      ));
    }
    if (path.endsWith(`/${first.queuedTurn.id}/edit`) && method === "POST") {
      editRequested = true;
      return await editResponse.promise;
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await screen.findByRole("button", { name: "Edit queued Turn 2" });
  await user.click(screen.getByRole("button", { name: "Edit queued Turn 2" }));
  const firstEditor = screen.getByLabelText("Edit queued Turn 2") as HTMLTextAreaElement;
  await user.clear(firstEditor);
  await user.type(firstEditor, editedText);
  await user.click(screen.getByRole("button", { name: "Save queued Turn 2" }));
  await waitFor(() => assert.equal(editRequested, true));

  await user.click(screen.getByRole("button", { name: "Edit queued Turn 3" }));
  const secondEditor = screen.getByLabelText("Edit queued Turn 3") as HTMLTextAreaElement;
  await user.clear(secondEditor);
  await user.type(secondEditor, "Keep this newer editor focused");
  assert.equal(document.activeElement, secondEditor);

  await act(async () => {
    editResponse.resolve(Response.json(queueMutation("edited", editedText, 4, 3)));
    await editResponse.promise;
  });

  const currentSecondEditor = await screen.findByLabelText("Edit queued Turn 3") as HTMLTextAreaElement;
  await waitFor(() => assert.equal(document.activeElement, currentSecondEditor));
  assert.equal(currentSecondEditor.value, "Keep this newer editor focused");
});

test("Home Console does not let delayed cancellation steal focus from a newer Turn editor", async () => {
  const first = queuedFixture();
  const second = secondQueuedFixture();
  const cancelResponse = deferredResponse();
  let cancelled = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(
        null,
        conversation,
        cancelled ? [second.queuedTurn] : [first.queuedTurn, second.queuedTurn],
        cancelled ? [second.queuedMessage] : [first.queuedMessage, second.queuedMessage],
      ));
    }
    if (path.endsWith(`/${first.queuedTurn.id}/cancel`) && method === "POST") {
      const response = await cancelResponse.promise;
      cancelled = true;
      return response;
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await screen.findByRole("button", { name: "Cancel queued Turn 2" });
  await user.click(screen.getByRole("button", { name: "Cancel queued Turn 2" }));
  await user.click(screen.getByRole("button", { name: "Edit queued Turn 3" }));
  const secondEditor = screen.getByLabelText("Edit queued Turn 3") as HTMLTextAreaElement;
  await user.clear(secondEditor);
  await user.type(secondEditor, "Cancellation must not move focus");
  assert.equal(document.activeElement, secondEditor);

  await act(async () => {
    cancelResponse.resolve(Response.json(queueMutation("cancelled", first.queuedTurn.text, 4, 3)));
    await cancelResponse.promise;
  });

  const currentSecondEditor = await screen.findByLabelText("Edit queued Turn 3") as HTMLTextAreaElement;
  await waitFor(() => assert.equal(document.activeElement, currentSecondEditor));
  assert.equal(currentSecondEditor.value, "Cancellation must not move focus");
  assert.equal(screen.queryByRole("button", { name: "Cancel queued Turn 2" }), null);
});

test("Home Console does not let delayed Continue steal focus from a newer Turn editor", async () => {
  const first = queuedFixture("blocked");
  const second = secondQueuedFixture();
  const submitted = acceptedQueuedSubmission(first.queuedTurn.text);
  const continueResponse = deferredResponse();
  let continued = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(
        continued ? submitted.run : null,
        conversation,
        continued ? [second.queuedTurn] : [first.queuedTurn, second.queuedTurn],
        continued
          ? [submitted.message, second.queuedMessage]
          : [first.queuedMessage, second.queuedMessage],
      ));
    }
    if (path.endsWith(`/${first.queuedTurn.id}/continue`) && method === "POST") {
      const response = await continueResponse.promise;
      continued = true;
      return response;
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await screen.findByRole("button", { name: "Continue queued Turn 2" });
  await user.click(screen.getByRole("button", { name: "Continue queued Turn 2" }));
  await user.click(screen.getByRole("button", { name: "Edit queued Turn 3" }));
  const secondEditor = screen.getByLabelText("Edit queued Turn 3") as HTMLTextAreaElement;
  await user.clear(secondEditor);
  await user.type(secondEditor, "Continue must preserve this editor");
  assert.equal(document.activeElement, secondEditor);

  await act(async () => {
    continueResponse.resolve(Response.json(submitted, { status: 202 }));
    await continueResponse.promise;
  });

  const currentSecondEditor = await screen.findByLabelText("Edit queued Turn 3") as HTMLTextAreaElement;
  await waitFor(() => assert.equal(document.activeElement, currentSecondEditor));
  assert.equal(currentSecondEditor.value, "Continue must preserve this editor");
  assert.equal(screen.queryByRole("button", { name: "Continue queued Turn 2" }), null);
});

test("Home Console explicitly continues the blocked FIFO head after exact revalidation", async () => {
  const fixture = queuedFixture("blocked");
  const submitted = acceptedQueuedSubmission(fixture.queuedTurn.text);
  const calls: Array<{ body: string | undefined; method: string; path: string }> = [];
  let continued = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    calls.push({ body: init?.body?.toString(), method, path });
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(continued
        ? detail(submitted.run, submitted.conversation, [], [submitted.message])
        : detail(null, conversation, [fixture.queuedTurn], [fixture.queuedMessage]));
    }
    if (path.endsWith(`/${fixture.queuedTurn.id}/continue`) && method === "POST") {
      continued = true;
      return Response.json(submitted, { status: 202 });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await screen.findByRole("button", { name: "Continue queued Turn 2" });
  assert.match(screen.getByLabelText("Queued Turns").textContent ?? "", /Blocked: Failed/u);
  await user.click(screen.getByRole("button", { name: "Continue queued Turn 2" }));

  await waitFor(() => assert.equal(screen.queryByLabelText("Queued Turns"), null));
  await waitFor(() => assert.equal(document.activeElement, screen.getByLabelText("Prompt")));
  assert.equal(screen.getByRole("status").textContent, "Turn #2 started after exact revalidation.");
  assert.match(document.querySelector(".selected-run-progress")?.textContent ?? "", /Run Starting/u);
  const call = calls.find((item) => item.path.endsWith("/continue") && item.method === "POST");
  assert.ok(call);
  assert.deepEqual(JSON.parse(call.body ?? "{}"), {
    expected_message_revision: 2,
    expected_revision: 3,
  });
});

test("Home Console steers only the exact running Run and keeps an unverifiable draft", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", {
    configurable: true,
    value: MockEventSource,
  });
  const activeRun = {
    id: "run_steer",
    partial: false,
    status: "running",
    updated_at: timestamp,
  };
  const calls: Array<{ body: string | undefined; method: string; path: string }> = [];
  let attempts = 0;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    calls.push({ body: init?.body?.toString(), method, path });
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(activeRun));
    }
    if (path === `/api/conversations/${conversation.id}/steer` && method === "POST") {
      attempts += 1;
      return attempts === 1
        ? Response.json({ schema_version: 1, status: "partial" }, { status: 500 })
        : attempts === 2
          ? Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 })
          : Response.json({
          action: "steer",
          conversation_id: conversation.id,
          disposition: "accepted",
          run_id: activeRun.id,
          runtime: "python",
          schema_version: 1,
          service: "mentat-local-bridge",
          status: "ready",
        });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const prompt = await screen.findByLabelText("Prompt") as HTMLTextAreaElement;
  await waitFor(() => assert.equal(prompt.disabled, false));
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));
  await act(async () => {
    MockEventSource.instances[0].emit("snapshot", JSON.stringify({
      event: { run_id: activeRun.id, summary: "Running" },
    }));
  });
  await waitFor(() => assert.match(
    document.querySelector(".selected-run-progress")?.textContent ?? "",
    /Run Running/u,
  ));
  await user.type(prompt, "   /steer focus only on the final answer");
  assert.equal(screen.queryByRole("button", { name: "Steer" }), null);
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /may have received this steering/u));
  assert.equal(prompt.value, "   /steer focus only on the final answer");

  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /temporarily unavailable/u));
  assert.equal(prompt.value, "   /steer focus only on the final answer");

  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => assert.equal(prompt.value, ""));
  assert.equal(screen.getByRole("status").textContent, "Steering was accepted by the exact active Run. It was not queued.");
  const steerCalls = calls.filter((call) => call.path.endsWith("/steer"));
  assert.equal(steerCalls.length, 3);
  for (const call of steerCalls) {
    assert.deepEqual(JSON.parse(call.body ?? "{}"), {
      run_id: activeRun.id,
      text: "focus only on the final answer",
    });
  }
  assert.equal(calls.some((call) => call.path.endsWith("/turns")), false);
});

test("Home Console previews and confirms Stop without closing the Conversation", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", { configurable: true, value: MockEventSource });
  const stoppableAgent = { ...agent, capabilities: [...agent.capabilities, "run.stop"] };
  const activeRun = { id: "run_stop_home", partial: false, status: "running", updated_at: timestamp };
  let stopped = false;
  const calls: Array<{ body: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, agents: [stoppableAgent] });
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(stopped ? null : activeRun, conversation, [], [], stoppableAgent));
    if (path.endsWith("/stop/preview") && method === "POST") {
      calls.push({ body: String(init?.body), path });
      return Response.json({ action: "stop", confirmation_id: "a".repeat(64), requires_confirmation: true, run_id: activeRun.id, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    }
    if (path.endsWith("/stop") && method === "POST") {
      calls.push({ body: String(init?.body), path });
      stopped = true;
      return Response.json({ action: "stop", disposition: "requested", run_id: activeRun.id, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }, { status: 202 });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));
  await act(async () => MockEventSource.instances[0].emit("snapshot", JSON.stringify({ event: { run_id: activeRun.id, summary: "Running" } })));
  await user.click(await screen.findByRole("button", { name: "Stop" }));
  await user.click(await screen.findByRole("button", { name: "Confirm Stop" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /Conversation remains open/u));
  assert.ok(document.getElementById(`conversation-tab-${conversation.id}`));
  assert.deepEqual(calls, [
    { body: "{}", path: `/api/runs/${activeRun.id}/stop/preview` },
    { body: `{"confirmation_id":"${"a".repeat(64)}"}`, path: `/api/runs/${activeRun.id}/stop` },
  ]);
});

test("Home Console keeps approval in a dedicated card and confirms the exact response", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", { configurable: true, value: MockEventSource });
  const waitingRun = { id: "run_approval_home", partial: false, status: "waiting_for_approval", updated_at: timestamp };
  const request = { kind: "approval", title: "Use a tool", summary: "Read project data", choices: [{ id: "once", label: "Allow once" }, { id: "deny", label: "Deny" }] };
  let answered = false;
  const calls: string[] = [];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(answered ? { ...waitingRun, status: "running" } : waitingRun));
    if (path.endsWith("/response/preview") && method === "POST") return Response.json({ action: "respond", confirmation_id: "b".repeat(64), request, requires_confirmation: true, run_id: waitingRun.id, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    if (path.endsWith("/response") && method === "POST") {
      calls.push(String(init?.body));
      if (String(init?.body) === "{}") return Response.json({ action: "respond", request, requires_confirmation: false, run_id: waitingRun.id, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
      answered = true;
      return Response.json({ action: "respond", disposition: "accepted", run_id: waitingRun.id, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }, { status: 202 });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));
  await act(async () => MockEventSource.instances[0].emit("snapshot", JSON.stringify({ event: { run_id: waitingRun.id, summary: "Waiting" } })));
  const card = await screen.findByLabelText("Approval required");
  assert.match(card.textContent ?? "", /prompt composer cannot answer/u);
  await user.click(screen.getByRole("button", { name: "Allow once" }));
  await user.click(await screen.findByRole("button", { name: "Confirm response" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /Response accepted/u));
  assert.equal(calls.some((body) => body.includes('"kind":"approval"')), true);
  assert.equal(calls.some((body) => body.includes("idempotency_key")), false);
});

test("Home Console closes, reopens, archives, and restores without deleting history", async () => {
  let state = { ...conversation } as ConversationFixture;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, conversations: [state] });
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(null, state));
    if ((path.endsWith("/archive") || path.endsWith("/restore")) && method === "POST") {
      const archived = path.endsWith("/archive");
      state = { ...state, archived_at: archived ? timestamp : null, revision: state.revision + 1, state: archived ? "archived" as const : "active" as const };
      return Response.json({ action: archived ? "archive" : "restore", conversation: state, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await screen.findByLabelText("Prompt");
  await user.click(screen.getByRole("button", { name: "Close New conversation tab" }));
  assert.equal(document.getElementById(`conversation-tab-${conversation.id}`), null);
  await waitFor(() => assert.equal(document.activeElement?.id, "recent-conversations-summary"));
  await user.click(screen.getByText("Recent Conversations"));
  await user.click(document.querySelector<HTMLButtonElement>(".history-open")!);
  assert.ok(document.getElementById(`conversation-tab-${conversation.id}`));
  await user.click(screen.getByRole("button", { name: "Archive New conversation" }));
  await waitFor(() => assert.equal((screen.getByLabelText("Prompt") as HTMLTextAreaElement).value, ""));
  assert.equal((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled, true);
  await user.click(screen.getByRole("button", { name: "Restore New conversation" }));
  await waitFor(() => assert.equal(screen.getByRole("button", { name: "Archive New conversation" }).getAttribute("disabled"), null));
});

test("Home Console creates one exact Retry Run and preserves the prior failure", async () => {
  const failedRun = { id: "run_failed_home", partial: false, status: "failed", updated_at: timestamp };
  const retryRun = { id: "run_retry_home", partial: false, status: "starting", updated_at: "2026-08-26T12:01:00Z" };
  let retried = false;
  const retryBodies: Array<Record<string, unknown>> = [];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(retried ? retryRun : failedRun));
    if (path === `/api/conversations/${conversation.id}/retry` && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      retryBodies.push(body);
      retried = true;
      return Response.json({ action: "retry", conversation_id: conversation.id, duplicate: false, run: retryRun, runtime: "python", schema_version: 1, service: "mentat-local-bridge", source_run_id: failedRun.id, status: "ready" }, { status: 202 });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const recovery = await screen.findByLabelText("Run recovery");
  assert.match(recovery.textContent ?? "", /prior Run and its events remain in history/u);
  assert.equal(screen.queryByRole("button", { name: "Resume" }), null);
  await user.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /Retry accepted as a new Run/u));
  assert.equal(retryBodies.length, 1);
  assert.equal(retryBodies[0].source_run_id, failedRun.id);
  assert.equal(typeof retryBodies[0].idempotency_key, "string");
  assert.match(document.querySelector(".selected-run-progress")?.textContent ?? "", /Run Starting/u);
});

test("Home Console keeps a duplicate Retry replay reconciling until exact readback", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", { configurable: true, value: MockEventSource });
  const failedRun = { id: "run_failed_duplicate", partial: false, status: "failed", updated_at: timestamp };
  const replayedRun = { id: "run_retry_duplicate", partial: false, status: "starting", updated_at: timestamp };
  let replayed = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(replayed ? replayedRun : failedRun));
    if (path === `/api/conversations/${conversation.id}/retry` && method === "POST") {
      replayed = true;
      return Response.json({ action: "retry", conversation_id: conversation.id, duplicate: true, run: replayedRun, runtime: "python", schema_version: 1, service: "mentat-local-bridge", source_run_id: failedRun.id, status: "ready" });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await user.click(await screen.findByRole("button", { name: "Retry" }));
  await waitFor(() => assert.match(document.querySelector(".selected-run-progress")?.textContent ?? "", /Run Reconciling/u));
  assert.equal(screen.queryByRole("button", { name: "Stop" }), null);
  assert.equal(MockEventSource.instances.length, 1);
});

test("Home Console previews and confirms one exact Hermes next-Run configuration", async () => {
  const hermesAgent = { ...agent, id: "agent_hermes_config", name: "Hermes Builder", runtime_type: "hermes" };
  const hermesConversation = { ...conversation, agent_id: hermesAgent.id };
  let configured = false;
  const calls: Array<{ body: string; path: string }> = [];
  const configuration = () => ({
    active_run: false,
    agent_id: hermesAgent.id,
    current: { effort: "runtime_default", model: configured ? "claude-next" : "gpt-current", provider: configured ? "anthropic" : "openai" },
    efforts: [{ id: "runtime_default", name: "Runtime default" }],
    explanation: "",
    mutable: true,
    providers: [{ current: !configured, id: "openai", models: ["gpt-current"], name: "OpenAI" }, { current: configured, id: "anthropic", models: ["claude-next"], name: "Anthropic" }],
    runtime_type: "hermes",
    schema_version: 1,
    state: "ready",
  });
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, agents: [hermesAgent], conversations: [hermesConversation], direct_agent_id: null });
    if (path === "/api/agent-activity" && method === "GET") return Response.json({ ...activity, activity: [], direct_agent_id: null });
    if (path === `/api/conversations/${hermesConversation.id}` && method === "GET") return Response.json(detail(null, hermesConversation, [], [], hermesAgent));
    if (path === `/api/agents/${hermesAgent.id}/configuration` && method === "GET") return Response.json({ configuration: configuration(), runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    if (path.endsWith("/configuration/preview") && method === "POST") {
      calls.push({ body: String(init?.body), path });
      return Response.json({ action: "configure", agent_id: hermesAgent.id, confirmation_id: "provider_switch_" + "a".repeat(24), current: { model: "gpt-current", provider: "openai" }, message: "Next Run", requires_confirmation: true, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready", target: { effort: "runtime_default", model: "claude-next", provider: "anthropic", provider_name: "Anthropic" } });
    }
    if (path.endsWith("/configuration") && method === "POST") {
      calls.push({ body: String(init?.body), path });
      configured = true;
      return Response.json({ action: "configure", agent_id: hermesAgent.id, configuration: configuration(), message: "Verified", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const provider = await screen.findByLabelText("Provider for next Run") as HTMLSelectElement;
  await waitFor(() => assert.equal(provider.disabled, false));
  await user.selectOptions(provider, "anthropic");
  assert.equal((screen.getByLabelText("Model for next Run") as HTMLSelectElement).value, "claude-next");
  await user.click(screen.getByRole("button", { name: "Review" }));
  assert.match((await screen.findByText(/Anthropic · claude-next · next Run/u)).textContent ?? "", /next Run/u);
  const confirm = screen.getByRole("button", { name: "Confirm" });
  await waitFor(() => assert.equal(document.activeElement, confirm));
  await user.click(confirm);
  await waitFor(() => assert.match(screen.getByRole("status").textContent ?? "", /next Run will use it/u));
  await waitFor(() => assert.equal(document.activeElement, provider));
  assert.equal(provider.value, "anthropic");
  assert.deepEqual(calls, [
    { body: '{"provider":"anthropic","model":"claude-next"}', path: `/api/agents/${hermesAgent.id}/configuration/preview` },
    { body: `{"confirmation_id":"provider_switch_${"a".repeat(24)}","provider":"anthropic","model":"claude-next"}`, path: `/api/agents/${hermesAgent.id}/configuration` },
  ]);
});

test("Home Console keeps active Run configuration visible and selectors read-only", async () => {
  const activeRun = { configuration: { effort: "high", model: "gpt-active", provider: "openai" }, id: "run_config_snapshot", partial: false, status: "running", updated_at: timestamp };
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(activeRun));
    if (path === `/api/agents/${agent.id}/configuration` && method === "GET") return Response.json({ configuration: { active_run: true, agent_id: agent.id, current: { effort: "runtime_default", model: "Codex default", provider: "OpenAI" }, efforts: [{ id: "runtime_default", name: "Runtime default" }], explanation: "Codex is read-only.", mutable: false, providers: [], runtime_type: "codex", schema_version: 1, state: "read_only" }, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  render(<HomeConsole />);
  assert.match((await screen.findByText(/Active snapshot:/u)).textContent ?? "", /Openai · gpt-active · High/iu);
  assert.equal((screen.getByLabelText("Provider for next Run") as HTMLSelectElement).disabled, true);
  assert.match(document.querySelector(".configuration-explanation")?.textContent ?? "", /Active Run snapshot is unchanged/u);
});

test("Home Console invalidates a pending configuration preview when a Run starts", async () => {
  const hermesAgent = { ...agent, id: "agent_preview_active", name: "Hermes Active", runtime_type: "hermes" };
  const hermesConversation = { ...conversation, agent_id: hermesAgent.id };
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, agents: [hermesAgent], conversations: [hermesConversation], direct_agent_id: null });
    if (path === "/api/agent-activity" && method === "GET") return Response.json({ ...activity, activity: [], direct_agent_id: null });
    if (path === `/api/conversations/${hermesConversation.id}` && method === "GET") return Response.json(detail(null, hermesConversation, [], [], hermesAgent));
    if (path === `/api/agents/${hermesAgent.id}/configuration` && method === "GET") return Response.json({ configuration: { active_run: false, agent_id: hermesAgent.id, current: { effort: "runtime_default", model: "gpt", provider: "openai" }, efforts: [{ id: "runtime_default", name: "Runtime default" }], explanation: "", mutable: true, providers: [{ current: true, id: "openai", models: ["gpt"], name: "OpenAI" }, { current: false, id: "anthropic", models: ["claude"], name: "Anthropic" }], runtime_type: "hermes", schema_version: 1, state: "ready" }, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    if (path.endsWith("/configuration/preview") && method === "POST") return Response.json({ action: "configure", agent_id: hermesAgent.id, confirmation_id: "provider_switch_" + "c".repeat(24), current: { model: "gpt", provider: "openai" }, message: "Next Run", requires_confirmation: true, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready", target: { effort: "runtime_default", model: "claude", provider: "anthropic", provider_name: "Anthropic" } });
    if (path === `/api/conversations/${hermesConversation.id}/turns` && method === "POST") return Response.json(acceptedSubmission("Start with the old snapshot", hermesConversation), { status: 202 });
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const provider = await screen.findByLabelText("Provider for next Run") as HTMLSelectElement;
  await waitFor(() => assert.equal(provider.disabled, false));
  await user.selectOptions(provider, "anthropic");
  await user.click(screen.getByRole("button", { name: "Review" }));
  await screen.findByRole("button", { name: "Confirm" });
  const prompt = screen.getByLabelText("Prompt") as HTMLTextAreaElement;
  await user.type(prompt, "Start with the old snapshot");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  assert.equal(screen.queryByRole("button", { name: "Confirm" }), null);
  assert.match(document.querySelector(".configuration-explanation")?.textContent ?? "", /Active Run snapshot is unchanged/u);
});

test("Home Console rejects a delayed Agent configuration read after tab handoff", async () => {
  const firstAgent = { ...agent, id: "agent_config_first", name: "First Agent", runtime_type: "hermes" };
  const secondAgent = { ...agent, id: "agent_config_second", name: "Second Agent", runtime_type: "hermes" };
  const firstConversation = { ...conversation, agent_id: firstAgent.id };
  const secondConversation = { ...conversation, agent_id: secondAgent.id, id: "conv_config_second", title: "Second configuration", title_source: "first_prompt" as const };
  let resolveFirst: ((response: Response) => void) | null = null;
  const firstConfiguration = new Promise<Response>((resolve) => { resolveFirst = resolve; });
  const configuration = (targetAgent: typeof firstAgent, provider: string) => ({ configuration: { active_run: false, agent_id: targetAgent.id, current: { effort: "runtime_default", model: `${provider}-model`, provider }, efforts: [{ id: "runtime_default", name: "Runtime default" }], explanation: "", mutable: true, providers: [{ current: true, id: provider, models: [`${provider}-model`], name: provider }], runtime_type: "hermes", schema_version: 1, state: "ready" }, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, agents: [firstAgent, secondAgent], conversations: [firstConversation, secondConversation], count: 2, direct_agent_id: null });
    if (path === "/api/agent-activity" && method === "GET") return Response.json({ ...activity, activity: [], direct_agent_id: null });
    if (path === `/api/conversations/${firstConversation.id}` && method === "GET") return Response.json(detail(null, firstConversation, [], [], firstAgent));
    if (path === `/api/conversations/${secondConversation.id}` && method === "GET") return Response.json(detail(null, secondConversation, [], [], secondAgent));
    if (path === `/api/agents/${firstAgent.id}/configuration` && method === "GET") return await firstConfiguration;
    if (path === `/api/agents/${secondAgent.id}/configuration` && method === "GET") return Response.json(configuration(secondAgent, "second-provider"));
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  render(<HomeConsole />);
  await screen.findByLabelText("Prompt");
  await waitFor(() => assert.ok(document.getElementById(`conversation-tab-${secondConversation.id}`)));
  fireEvent.click(document.getElementById(`conversation-tab-${secondConversation.id}`)!);
  const provider = screen.getByLabelText("Provider for next Run") as HTMLSelectElement;
  await waitFor(() => assert.equal(provider.value, "second-provider"));
  await act(async () => { resolveFirst?.(Response.json(configuration(firstAgent, "first-provider"))); await firstConfiguration; });
  await waitFor(() => assert.equal(provider.value, "second-provider"));
  assert.equal((screen.getByLabelText("Conversation Agent") as HTMLSelectElement).value, secondAgent.id);
});

test("Home Console never configures the picker Agent while Conversation detail is unresolved", async () => {
  const pickerAgent = { ...agent, id: "agent_picker_only", name: "Picker Agent", runtime_type: "hermes" };
  const boundAgent = { ...agent, id: "agent_bound_detail", name: "Bound Agent", runtime_type: "hermes" };
  const boundConversation = { ...conversation, agent_id: boundAgent.id };
  let resolveDetail: ((response: Response) => void) | null = null;
  const delayedDetail = new Promise<Response>((resolve) => { resolveDetail = resolve; });
  const configurationCalls: string[] = [];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, agents: [pickerAgent, boundAgent], conversations: [boundConversation], direct_agent_id: pickerAgent.id });
    if (path === "/api/agent-activity" && method === "GET") return Response.json({ ...activity, activity: [], direct_agent_id: pickerAgent.id });
    if (path === `/api/conversations/${boundConversation.id}` && method === "GET") return await delayedDetail;
    if (path.startsWith("/api/agents/") && path.endsWith("/configuration")) {
      configurationCalls.push(path);
      return Response.json({ configuration: { active_run: false, agent_id: boundAgent.id, current: { effort: "runtime_default", model: "bound-model", provider: "bound-provider" }, efforts: [{ id: "runtime_default", name: "Runtime default" }], explanation: "", mutable: true, providers: [{ current: true, id: "bound-provider", models: ["bound-model"], name: "Bound" }], runtime_type: "hermes", schema_version: 1, state: "ready" }, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  render(<HomeConsole />);
  const composerAgent = await screen.findByLabelText("Conversation Agent") as HTMLSelectElement;
  assert.equal(composerAgent.disabled, true);
  assert.equal(composerAgent.value, "");
  assert.deepEqual(configurationCalls, []);
  assert.equal(screen.queryByRole("button", { name: "Review" }), null);
  await act(async () => { resolveDetail?.(Response.json(detail(null, boundConversation, [], [], boundAgent))); await delayedDetail; });
  await waitFor(() => assert.deepEqual(configurationCalls, [`/api/agents/${boundAgent.id}/configuration`]));
  assert.equal(composerAgent.value, boundAgent.id);
});

test("Home Console distinguishes unavailable, unsupported, and unsafe configuration reads", async () => {
  for (const [status, code, copy] of [
    ["unavailable", 503, /temporarily unavailable/u],
    ["unsupported", 501, /does not support Agent configuration/u],
    ["error", 502, /could not be read safely/u],
  ] as const) {
    globalThis.fetch = async (input, init) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path === "/api/conversations" && method === "GET") return Response.json(list);
      if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
      if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(null));
      if (path === `/api/agents/${agent.id}/configuration` && method === "GET") return Response.json({ schema_version: 1, status }, { status: code });
      throw new Error(`Unexpected fetch: ${method} ${path}`);
    };
    const rendered = render(<HomeConsole />);
    await waitFor(() => assert.match(document.querySelector(".configuration-explanation")?.textContent ?? "", copy));
    assert.equal(screen.queryByRole("button", { name: "Review" }), null);
    rendered.unmount();
  }
});

test("Home Console scopes same-Agent preview and confirmed refresh to the selected tab", async () => {
  const secondConversation = { ...conversation, id: "conv_same_agent_second", title: "Same Agent second", title_source: "first_prompt" as const };
  let configured = false;
  let delayPreview = true;
  let resolvePreview: ((response: Response) => void) | null = null;
  let resolveConfirm: ((response: Response) => void) | null = null;
  let configurationReads = 0;
  const delayedPreview = new Promise<Response>((resolve) => { resolvePreview = resolve; });
  const delayedConfirm = new Promise<Response>((resolve) => { resolveConfirm = resolve; });
  const config = () => ({ configuration: { active_run: false, agent_id: agent.id, current: { effort: "runtime_default", model: configured ? "claude" : "gpt", provider: configured ? "anthropic" : "openai" }, efforts: [{ id: "runtime_default", name: "Runtime default" }], explanation: "", mutable: true, providers: [{ current: !configured, id: "openai", models: ["gpt"], name: "OpenAI" }, { current: configured, id: "anthropic", models: ["claude"], name: "Anthropic" }], runtime_type: "hermes", schema_version: 1, state: "ready" }, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
  const previewResponse = () => Response.json({ action: "configure", agent_id: agent.id, confirmation_id: "provider_switch_" + "b".repeat(24), current: { model: "gpt", provider: "openai" }, message: "Next Run", requires_confirmation: true, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready", target: { effort: "runtime_default", model: "claude", provider: "anthropic", provider_name: "Anthropic" } });
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, conversations: [conversation, secondConversation], count: 2 });
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(null));
    if (path === `/api/conversations/${secondConversation.id}` && method === "GET") return Response.json(detail(null, secondConversation));
    if (path === `/api/agents/${agent.id}/configuration` && method === "GET") { configurationReads += 1; return Response.json(config()); }
    if (path.endsWith("/configuration/preview") && method === "POST") {
      if (delayPreview) return await delayedPreview;
      return previewResponse();
    }
    if (path.endsWith("/configuration") && method === "POST") return await delayedConfirm;
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const provider = await screen.findByLabelText("Provider for next Run") as HTMLSelectElement;
  await waitFor(() => assert.equal(provider.disabled, false));
  await user.selectOptions(provider, "anthropic");
  await user.click(screen.getByRole("button", { name: "Review" }));
  fireEvent.click(document.getElementById(`conversation-tab-${secondConversation.id}`)!);
  await act(async () => { resolvePreview?.(previewResponse()); await delayedPreview; });
  await waitFor(() => assert.equal(screen.queryByRole("button", { name: "Confirm" }), null));

  fireEvent.click(document.getElementById(`conversation-tab-${conversation.id}`)!);
  await waitFor(() => assert.equal(provider.value, "openai"));
  await user.selectOptions(provider, "anthropic");
  delayPreview = false;
  await user.click(screen.getByRole("button", { name: "Review" }));
  await user.click(await screen.findByRole("button", { name: "Confirm" }));
  fireEvent.click(document.getElementById(`conversation-tab-${secondConversation.id}`)!);
  configured = true;
  await act(async () => {
    resolveConfirm?.(Response.json({ action: "configure", agent_id: agent.id, configuration: config().configuration, message: "Verified", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }));
    await delayedConfirm;
  });
  await waitFor(() => assert.equal(provider.value, "anthropic"));
  assert.ok(configurationReads >= 5);
  assert.equal(screen.queryByRole("button", { name: "Confirm" }), null);
});

test("Home Console hides Resume when only the Agent declaration advertises it", async () => {
  const resumableAgent = { ...agent, capabilities: [...agent.capabilities, "run.resume"].sort() };
  const stoppedRun = { id: "run_stopped_home", partial: false, status: "stopped", updated_at: timestamp };
  const paths: string[] = [];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    paths.push(`${method} ${path}`);
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, agents: [resumableAgent] });
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(stoppedRun, conversation, [], [], resumableAgent));
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  render(<HomeConsole />);
  await screen.findByLabelText("Run recovery");
  assert.equal(screen.queryByRole("button", { name: "Resume" }), null);
  assert.equal(paths.includes(`POST /api/conversations/${conversation.id}/resume`), false);
});

test("Home Console never offers Retry for active partial or unknown Runs", async () => {
  for (const status of ["running", "waiting_for_approval", "unknown"]) {
    installFetch({ currentRun: { id: `run_${status}`, partial: true, status, updated_at: timestamp } });
    const rendered = render(<HomeConsole />);
    await screen.findByLabelText("Prompt");
    assert.equal(screen.queryByLabelText("Run recovery"), null, status);
    assert.equal(screen.queryByRole("button", { name: "Retry" }), null, status);
    rendered.unmount();
  }
});

test("Home Console keeps each terminal outcome visible when verification is partial", async () => {
  for (const status of ["failed", "stopped", "interrupted", "completed"]) {
    installFetch({ currentRun: { id: `run_partial_${status}`, partial: true, status, updated_at: timestamp } });
    const rendered = render(<HomeConsole />);
    const recovery = await screen.findByLabelText("Run recovery");
    assert.match(recovery.textContent ?? "", new RegExp(`Run ${status}`, "iu"), status);
    assert.match(recovery.textContent ?? "", /verification partial/iu, status);
    rendered.unmount();
  }
});

test("Home Console opens a tab for an activity Conversation outside the loaded page", async () => {
  const unloaded = { ...conversation, id: "conv_unloaded_activity", title: "Unloaded work", title_source: "first_prompt" as const };
  const unloadedActivity = {
    ...activity,
    activity: [{
      agent,
      attention: true,
      conversations: [{ attention: true, id: unloaded.id, run_id: "run_unloaded_activity", run_status: "failed", title: unloaded.title, updated_at: timestamp }],
      state: "failed",
      summary: unloaded.title,
      updated_at: timestamp,
    }],
  };
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, conversations: [], count: 0 });
    if (path === "/api/agent-activity" && method === "GET") return Response.json(unloadedActivity);
    if (path === `/api/conversations/${unloaded.id}` && method === "GET") return Response.json(detail({ id: "run_unloaded_activity", partial: false, status: "failed", updated_at: timestamp }, unloaded));
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await user.click(await screen.findByRole("button", { name: new RegExp(agent.name, "u") }));
  await user.click(screen.getByRole("button", { name: unloaded.title }));
  await waitFor(() => assert.ok(document.getElementById(`conversation-tab-${unloaded.id}`)));
  assert.equal(document.getElementById(`conversation-tab-${unloaded.id}`)?.getAttribute("aria-selected"), "true");
});

test("Home Console streams only the selected Run and reconciles durable completion", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", {
    configurable: true,
    value: MockEventSource,
  });
  const otherConversation = {
    ...conversation,
    id: "conv_background",
    title: "Background work",
    title_source: "first_prompt",
  };
  const activeRun = {
    id: "run_stream",
    partial: false,
    status: "running",
    updated_at: timestamp,
  };
  const userMessage = transcriptMessage(1, "user", "Do the work", activeRun.id);
  const assistantMessage = transcriptMessage(2, "assistant", "Durable final answer", activeRun.id);
  let completed = false;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") {
      return Response.json({ ...list, conversations: [conversation, otherConversation], count: 2 });
    }
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(completed
        ? detail(null, conversation, [], [userMessage, assistantMessage])
        : detail(activeRun, conversation, [], [userMessage]));
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  render(<HomeConsole />);
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));
  const source = MockEventSource.instances[0];
  assert.equal(source.url, `/api/runs/${activeRun.id}/events`);
  const liveUpdateStartedAt = performance.now();
  await act(async () => {
    source.emit("snapshot", JSON.stringify({
      event: {
        private_runtime_payload: "must not render",
        run_id: activeRun.id,
        summary: "Verifying the selected Run",
      },
    }));
  });
  await waitFor(() => assert.match(
    document.querySelector(".selected-run-progress")?.textContent ?? "",
    /Verifying the selected Run/u,
  ), { interval: 5, timeout: 250 });
  assert.ok(performance.now() - liveUpdateStartedAt < 250);
  assert.doesNotMatch(document.body.textContent ?? "", /private_runtime_payload/u);

  completed = true;
  await act(async () => {
    source.emit("timeline", JSON.stringify({
      event: { run_id: activeRun.id, summary: "Completed" },
    }));
  });
  await screen.findByText("Durable final answer");
  await waitFor(() => assert.equal(source.closed, true));
  assert.equal(MockEventSource.instances.length, 1);
  assert.equal(MockEventSource.instances.some((item) => item.url.includes("background")), false);
});

test("Home Console opens genuine Thinking, collapses on later Activity, and keeps raw payloads hidden", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", { configurable: true, value: MockEventSource });
  const activeRun = { id: "run_safe_presentation", partial: false, status: "running", updated_at: timestamp };
  installFetch({ currentRun: activeRun });
  const event = (sequence: number, type: string, summary: string, presentation: Record<string, string> | null) => ({ id: `event_safe_${sequence}`, message: null, metrics: {}, occurred_at: timestamp, presentation, raw_reasoning: "must never render", run_id: activeRun.id, sequence, summary, tool_arguments: { path: "/private/secret" }, type });
  render(<HomeConsole />);
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));
  await act(async () => MockEventSource.instances[0].emit("snapshot", JSON.stringify({ events: [event(1, "message", "Reasoning summary available", { kind: "reasoning", label: "Reasoning summary available", phase: "available" })], reset: false })));
  const thinkingSummary = await screen.findByText("Thinking…");
  const thinking = thinkingSummary.closest("details") as HTMLDetailsElement;
  await waitFor(() => assert.equal(thinking.open, true));
  assert.equal(document.body.textContent?.includes("must never render"), false);
  assert.equal(document.body.textContent?.includes("/private/secret"), false);

  await act(async () => MockEventSource.instances[0].emit("timeline", JSON.stringify({ event: event(2, "run.progress", "Run progress", null) })));
  await waitFor(() => assert.equal(thinking.open, false));
  await act(async () => MockEventSource.instances[0].emit("timeline", JSON.stringify({ event: event(3, "tool.requested", "Tool activity started", { kind: "tool", label: "Tool activity started", phase: "started" }) })));
  await waitFor(() => assert.equal(thinking.open, false));
  await waitFor(() => assert.equal(document.querySelector(".presentation-announcement")?.textContent, "Agent activity started."));
  const activitySummary = await screen.findByText("Activity in progress");
  const activityDetails = activitySummary.closest("details") as HTMLDetailsElement;
  assert.equal(activityDetails.open, false);
  await act(async () => MockEventSource.instances[0].emit("snapshot", JSON.stringify({ events: [], reset: false })));
  assert.equal(screen.getByText("Activity in progress").textContent, "Activity in progress");
  await userEvent.setup({ document: dom.window.document }).click(screen.getByText("Thinking"));
  assert.equal(thinking.open, true);

  await act(async () => MockEventSource.instances[0].emit("timeline", JSON.stringify({ event: event(4, "tool.completed", "Tool activity completed", { kind: "tool", label: "Tool activity completed", phase: "completed" }) })));
  await waitFor(() => assert.equal(document.querySelector(".presentation-announcement")?.textContent, "Agent activity finished."));

  await act(async () => MockEventSource.instances[0].emit("reset", JSON.stringify({ events: [event(3, "message", "Reasoning summary available", { kind: "reasoning", label: "Reasoning summary available", phase: "available" })] })));
  await screen.findByText("Thinking…");
  assert.equal(screen.queryByText(/Activity/u), null);
  await act(async () => MockEventSource.instances[0].emit("reset", JSON.stringify({ events: [] })));
  await waitFor(() => assert.equal(screen.queryByText(/^Thinking/u), null));
});

test("Home Console groups durable Run and queued Messages in screen-reader order", async () => {
  const base = {
    content: { parts: [{ text: "# Safe heading\n\n`inline` text", type: "text" }], schema_version: 1 },
    conversation_id: conversation.id,
    created_at: timestamp,
    revision: 1,
    state: "accepted",
    updated_at: timestamp,
  };
  const messages = [
    { ...base, id: "msg_group_1", role: "user", run_id: "run_group_1", sequence: 1 },
    { ...base, content: { parts: [{ text: "Queued follow-up", type: "text" }], schema_version: 1 }, id: "msg_group_2", role: "user", run_id: null, sequence: 2 },
    { ...base, content: { parts: [{ text: "First answer", type: "text" }], schema_version: 1 }, id: "msg_group_3", role: "assistant", run_id: "run_group_1", sequence: 3 },
    { ...base, content: { parts: [{ text: "Second queued follow-up", type: "text" }], schema_version: 1 }, id: "msg_group_4", role: "user", run_id: null, sequence: 4 },
    { ...base, content: { parts: [{ text: "Second answer", type: "text" }], schema_version: 1 }, id: "msg_group_5", role: "assistant", run_id: "run_group_2", sequence: 5 },
  ];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(null, conversation, [], messages));
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  render(<HomeConsole />);
  await waitFor(() => assert.equal(document.querySelectorAll(".message-row").length, 5));
  const groups = [...document.querySelectorAll<HTMLElement>(".message-group")];
  assert.deepEqual(groups.map((group) => group.getAttribute("aria-label")), ["Run 1", "Queued turn", "Run 1", "Queued turn", "Run 2"]);
  assert.deepEqual([...document.querySelectorAll(".message-row")].map((row) => row.textContent?.includes("First answer") ? "first-answer" : row.textContent?.includes("Second queued") ? "second-queued" : row.textContent?.includes("Queued follow-up") ? "queued" : row.textContent?.includes("Second answer") ? "second-answer" : "first-prompt"), ["first-prompt", "queued", "first-answer", "second-queued", "second-answer"]);
  assert.equal(screen.getByRole("heading", { name: "Safe heading" }).tagName, "H2");
});

test("Home Console isolates Thinking and Activity state across selected Runs", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", { configurable: true, value: MockEventSource });
  const secondConversation = { ...conversation, id: "conv_presentation_second", title: "Second live Run" };
  const firstRun = { id: "run_presentation_first", partial: false, status: "running", updated_at: timestamp };
  const secondRun = { id: "run_presentation_second", partial: false, status: "running", updated_at: timestamp };
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, conversations: [conversation, secondConversation], count: 2 });
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(firstRun));
    if (path === `/api/conversations/${secondConversation.id}` && method === "GET") return Response.json(detail(secondRun, secondConversation));
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  const event = (runId: string, sequence: number, type: string, summary: string, presentation: Record<string, string>) => ({ id: `event_${runId}_${sequence}`, message: null, metrics: {}, occurred_at: timestamp, presentation, run_id: runId, sequence, summary, type });
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));
  await act(async () => MockEventSource.instances[0].emit("snapshot", JSON.stringify({ events: [event(firstRun.id, 1, "message", "Reasoning summary available", { kind: "reasoning", label: "Reasoning summary available", phase: "available" })], reset: false })));
  const firstThinking = (await screen.findByText("Thinking…")).closest("details") as HTMLDetailsElement;
  await user.click(screen.getByText("Thinking…"));
  assert.equal(firstThinking.open, false);

  await user.click(document.getElementById(`conversation-tab-${secondConversation.id}`)!);
  await waitFor(() => assert.equal(MockEventSource.instances.length, 2));
  await act(async () => MockEventSource.instances[1].emit("snapshot", JSON.stringify({ events: [event(secondRun.id, 1, "message", "Reasoning summary available", { kind: "reasoning", label: "Reasoning summary available", phase: "available" })], reset: false })));
  const secondThinking = (await screen.findByText("Thinking…")).closest("details") as HTMLDetailsElement;
  assert.equal(secondThinking.open, true);
  await act(async () => MockEventSource.instances[1].emit("timeline", JSON.stringify({ event: event(secondRun.id, 2, "tool.requested", "Tool activity started", { kind: "tool", label: "Tool activity started", phase: "started" }) })));
  await waitFor(() => assert.equal(document.querySelector(".presentation-announcement")?.textContent, "Agent activity started."));
});

test("Home Console retains independent scroll anchors for equal-length Conversation tabs", async () => {
  const secondConversation = { ...conversation, id: "conv_scroll_second", title: "Second scroll position" };
  const message = (target: typeof conversation, id: string, text: string) => ({
    content: { parts: [{ text, type: "text" }], schema_version: 1 },
    conversation_id: target.id,
    created_at: timestamp,
    id,
    revision: 1,
    role: "assistant",
    run_id: "run_scroll",
    sequence: 1,
    state: "accepted",
    updated_at: timestamp,
  });
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json({ ...list, conversations: [conversation, secondConversation], count: 2 });
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") return Response.json(detail(null, conversation, [], [message(conversation, "msg_scroll_first", "First scroll transcript")]));
    if (path === `/api/conversations/${secondConversation.id}` && method === "GET") return Response.json(detail(null, secondConversation, [], [message(secondConversation, "msg_scroll_second", "Second scroll transcript")]));
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };
  render(<HomeConsole />);
  await screen.findByText("First scroll transcript");
  const transcript = document.querySelector(".conversation-transcript") as HTMLDivElement;
  Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 1_000 });
  Object.defineProperty(transcript, "clientHeight", { configurable: true, value: 200 });
  transcript.scrollTop = 120;
  fireEvent.scroll(transcript);

  fireEvent.click(document.getElementById(`conversation-tab-${secondConversation.id}`)!);
  await screen.findByText("Second scroll transcript");
  assert.equal(transcript.scrollTop, 1_000);
  transcript.scrollTop = 650;
  fireEvent.scroll(transcript);

  fireEvent.click(document.getElementById(`conversation-tab-${conversation.id}`)!);
  await screen.findByText("First scroll transcript");
  assert.equal(transcript.scrollTop, 120);
  fireEvent.click(document.getElementById(`conversation-tab-${secondConversation.id}`)!);
  await screen.findByText("Second scroll transcript");
  assert.equal(transcript.scrollTop, 650);
});

test("Home Console coalesces a live-event burst and rejects a trailing stale refresh", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", {
    configurable: true,
    value: MockEventSource,
  });
  const activeRun = {
    id: "run_burst",
    partial: false,
    status: "running",
    updated_at: timestamp,
  };
  const baseMessage = transcriptMessage(1, "assistant", "Initial durable state", activeRun.id);
  const freshMessage = {
    ...baseMessage,
    content: { parts: [{ text: "Fresh durable state", type: "text" }], schema_version: 1 },
    revision: 3,
    updated_at: "2026-08-26T12:01:00Z",
  };
  const staleMessage = {
    ...baseMessage,
    content: { parts: [{ text: "Stale state must not win", type: "text" }], schema_version: 1 },
    revision: 2,
    updated_at: "2026-08-26T12:00:30Z",
  };
  const freshConversation = {
    ...conversation,
    revision: 3,
    title: "Fresh title",
    title_source: "first_prompt",
    updated_at: "2026-08-26T12:01:00Z",
  };
  const staleConversation = {
    ...conversation,
    revision: 2,
    title: "Stale title",
    title_source: "first_prompt",
    updated_at: "2026-08-26T12:00:30Z",
  };
  const firstRefresh = deferredResponse();
  const trailingRefresh = deferredResponse();
  let bursting = false;
  let burstReads = 0;
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      if (!bursting) return Response.json(detail(activeRun, conversation, [], [baseMessage]));
      burstReads += 1;
      if (burstReads === 1) return await firstRefresh.promise;
      if (burstReads === 2) return await trailingRefresh.promise;
      throw new Error("A live burst performed more than one trailing refresh");
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  render(<HomeConsole />);
  await screen.findByText("Initial durable state");
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));
  const source = MockEventSource.instances[0];
  bursting = true;
  await act(async () => {
    for (let index = 0; index < 100; index += 1) {
      source.emit("timeline", JSON.stringify({
        event: { run_id: activeRun.id, summary: `Burst update ${index + 1}` },
      }));
    }
    await Promise.resolve();
  });
  assert.equal(burstReads, 1);

  firstRefresh.resolve(Response.json(detail(activeRun, freshConversation, [], [freshMessage])));
  await waitFor(() => assert.equal(burstReads, 2));
  trailingRefresh.resolve(Response.json(detail(activeRun, staleConversation, [], [staleMessage])));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });

  assert.equal(burstReads, 2);
  assert.equal(screen.getByText("Fresh durable state").textContent, "Fresh durable state");
  assert.equal(screen.queryByText("Stale state must not win"), null);
  assert.equal(document.getElementById(`conversation-tab-${conversation.id}`)?.textContent?.includes("Fresh title"), true);
  assert.match(document.querySelector(".selected-run-progress")?.textContent ?? "", /Burst update 100/u);
});

test("Home Console closes old streams and hands live progress across two active Runs", async () => {
  MockEventSource.instances = [];
  Object.defineProperty(globalThis, "EventSource", {
    configurable: true,
    value: MockEventSource,
  });
  const otherConversation = {
    ...conversation,
    id: "conv_handoff",
    title: "Handoff target",
    title_source: "first_prompt",
  };
  const firstRun = {
    id: "run_handoff_first",
    partial: false,
    status: "running",
    updated_at: timestamp,
  };
  const secondRun = {
    id: "run_handoff_second",
    partial: false,
    status: "running",
    updated_at: timestamp,
  };
  const reads = new Map<string, number>();
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") {
      return Response.json({ ...list, conversations: [conversation, otherConversation], count: 2 });
    }
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      reads.set(conversation.id, (reads.get(conversation.id) ?? 0) + 1);
      return Response.json(detail(firstRun, conversation, [], [
        transcriptMessage(1, "user", "First active Run", firstRun.id),
      ]));
    }
    if (path === `/api/conversations/${otherConversation.id}` && method === "GET") {
      reads.set(otherConversation.id, (reads.get(otherConversation.id) ?? 0) + 1);
      return Response.json(detail(secondRun, otherConversation, [], [{
        ...transcriptMessage(1, "user", "Second active Run", secondRun.id),
        conversation_id: otherConversation.id,
        id: "msg_handoff_second",
      }]));
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  render(<HomeConsole />);
  await waitFor(() => assert.equal(MockEventSource.instances.length, 1));
  const firstSource = MockEventSource.instances[0];
  assert.equal(firstSource.url, `/api/runs/${firstRun.id}/events`);
  await act(async () => {
    firstSource.onerror?.(new dom.window.Event("error") as unknown as Event);
  });
  await waitFor(() => assert.match(
    document.querySelector(".selected-run-progress")?.textContent ?? "",
    /Live updates are reconnecting/u,
  ));

  fireEvent.click(document.getElementById(`conversation-tab-${otherConversation.id}`)!);
  await screen.findByText("Second active Run");
  await waitFor(() => assert.equal(MockEventSource.instances.length, 2));
  const secondSource = MockEventSource.instances[1];
  assert.equal(firstSource.closed, true);
  assert.equal(secondSource.url, `/api/runs/${secondRun.id}/events`);
  const firstReadsAfterHandoff = reads.get(conversation.id);

  await act(async () => {
    firstSource.emit("timeline", JSON.stringify({
      event: { run_id: firstRun.id, summary: "Dropped old-stream update" },
    }));
    secondSource.emit("timeline", JSON.stringify({
      event: { run_id: firstRun.id, summary: "Wrong Run update" },
    }));
    secondSource.emit("reset", JSON.stringify({
      event: { run_id: secondRun.id, summary: "Second Run is live" },
    }));
  });
  await waitFor(() => assert.match(
    document.querySelector(".selected-run-progress")?.textContent ?? "",
    /Second Run is live/u,
  ));
  assert.doesNotMatch(document.body.textContent ?? "", /Dropped old-stream update|Wrong Run update/u);
  assert.equal(reads.get(conversation.id), firstReadsAfterHandoff);

  fireEvent.click(document.getElementById(`conversation-tab-${conversation.id}`)!);
  await screen.findByText("First active Run");
  await waitFor(() => assert.equal(MockEventSource.instances.length, 3));
  assert.equal(secondSource.closed, true);
  assert.equal(MockEventSource.instances[2].url, `/api/runs/${firstRun.id}/events`);
});

test("Home Console switches loaded tabs from cached canonical detail immediately", async () => {
  const otherConversation = {
    ...conversation,
    id: "conv_cached_other",
    title: "Cached other",
    title_source: "first_prompt",
  };
  const firstMessage = transcriptMessage(1, "assistant", "Cached first transcript");
  const otherMessage = {
    ...transcriptMessage(1, "assistant", "Cached other transcript"),
    conversation_id: otherConversation.id,
    id: "msg_cached_other",
  };
  let holdFirstRefresh = false;
  let resolveFirstRefresh: ((response: Response) => void) | undefined;
  const heldFirstRefresh = new Promise<Response>((resolve) => { resolveFirstRefresh = resolve; });
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") {
      return Response.json({ ...list, conversations: [conversation, otherConversation], count: 2 });
    }
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      if (holdFirstRefresh) return await heldFirstRefresh;
      return Response.json(detail(null, conversation, [], [firstMessage]));
    }
    if (path === `/api/conversations/${otherConversation.id}` && method === "GET") {
      return Response.json(detail(null, otherConversation, [], [otherMessage]));
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  render(<HomeConsole />);
  await screen.findByText("Cached first transcript");
  fireEvent.click(document.getElementById(`conversation-tab-${otherConversation.id}`)!);
  await screen.findByText("Cached other transcript");

  holdFirstRefresh = true;
  const switchStartedAt = performance.now();
  fireEvent.click(document.getElementById(`conversation-tab-${conversation.id}`)!);
  assert.equal(screen.getByText("Cached first transcript").textContent, "Cached first transcript");
  assert.ok(performance.now() - switchStartedAt < 50);
  await act(async () => {
    resolveFirstRefresh?.(Response.json(detail(null, conversation, [], [firstMessage])));
    await heldFirstRefresh;
  });
});

test("Home Console bounds a 100-message transcript and typing causes no network work", async () => {
  const messages = Array.from({ length: 100 }, (_, index) => transcriptMessage(
    index + 1,
    index % 2 === 0 ? "user" : "assistant",
    `Transcript message ${index + 1}`,
  ));
  const calls: string[] = [];
  globalThis.fetch = async (input, init) => {
    const path = pathOf(input);
    const method = init?.method ?? "GET";
    calls.push(`${method} ${path}`);
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      return Response.json(detail(null, conversation, [], messages));
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await waitFor(() => assert.equal(document.querySelectorAll(".message-row").length, 100));
  const callsAfterLoad = calls.length;
  const prompt = screen.getByLabelText("Prompt") as HTMLTextAreaElement;
  await user.type(prompt, "Typing remains entirely client-side");
  await act(async () => { await Promise.resolve(); });
  assert.equal(calls.length, callsAfterLoad);
  assert.equal(document.querySelectorAll(".message-row").length, 100);
});

test("Home Console enforces one aggregate formatting budget across 200 fragmented Messages", async () => {
  const fragmented = Array.from({ length: 200 }, (_, index) => `**token ${index}**`).join(" ");
  const olderMessages = Array.from({ length: 100 }, (_, index) => transcriptMessage(
    index + 1,
    index % 2 === 0 ? "user" : "assistant",
    fragmented,
  ));
  const recentMessages = Array.from({ length: 100 }, (_, index) => transcriptMessage(
    index + 101,
    index % 2 === 0 ? "user" : "assistant",
    fragmented,
  ));
  globalThis.fetch = async (input, init) => {
    const requestUrl = new URL(input instanceof Request ? input.url : input.toString(), origin);
    const path = requestUrl.pathname;
    const method = init?.method ?? "GET";
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      if (requestUrl.searchParams.get("before") === "101") return Response.json(detail(null, conversation, [], olderMessages));
      return Response.json({ ...detail(null, conversation, [], recentMessages), next_message_cursor: "101" });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await waitFor(() => assert.equal(document.querySelectorAll(".message-row").length, 100));
  await user.click(screen.getByRole("button", { name: "Load older messages" }));
  await waitFor(() => assert.equal(document.querySelectorAll(".message-row").length, 200));
  const formattedNodes = document.querySelectorAll(".transcript-markdown strong").length;
  assert.ok(formattedNodes > 0);
  assert.ok(formattedNodes <= transcriptContentLimits.maximumTranscriptRenderUnits / 2);
  assert.ok(screen.getAllByText("Formatting simplified for safe display.").length > 0);
});

test("Home Console retains a bounded 200-row transcript across older-message pagination", async () => {
  const olderMessages = Array.from({ length: 100 }, (_, index) => transcriptMessage(
    index + 1,
    index % 2 === 0 ? "user" : "assistant",
    `Paginated message ${index + 1}`,
  ));
  const recentMessages = Array.from({ length: 100 }, (_, index) => transcriptMessage(
    index + 101,
    index % 2 === 0 ? "user" : "assistant",
    `Paginated message ${index + 101}`,
  ));
  const calls: string[] = [];
  globalThis.fetch = async (input, init) => {
    const requestUrl = new URL(input instanceof Request ? input.url : input.toString(), origin);
    const path = requestUrl.pathname;
    const method = init?.method ?? "GET";
    calls.push(`${method} ${requestUrl.pathname}${requestUrl.search}`);
    if (path === "/api/conversations" && method === "GET") return Response.json(list);
    if (path === "/api/agent-activity" && method === "GET") return Response.json(activity);
    if (path === `/api/conversations/${conversation.id}` && method === "GET") {
      if (requestUrl.searchParams.get("before") === "101") {
        return Response.json(detail(null, conversation, [], olderMessages));
      }
      return Response.json({
        ...detail(null, conversation, [], recentMessages),
        next_message_cursor: "101",
      });
    }
    throw new Error(`Unexpected fetch: ${method} ${path}`);
  };

  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  await waitFor(() => assert.equal(document.querySelectorAll(".message-row").length, 100));
  await user.click(screen.getByRole("button", { name: "Load older messages" }));
  await waitFor(() => assert.equal(document.querySelectorAll(".message-row").length, 200));
  assert.equal(screen.getByText("Paginated message 1").textContent, "Paginated message 1");
  assert.equal(screen.getByText("Paginated message 200").textContent, "Paginated message 200");
  assert.equal(screen.queryByRole("button", { name: "Load older messages" }), null);
  assert.equal(calls.filter((call) => call.includes("?before=101")).length, 1);

  const callsAfterPagination = calls.length;
  await user.type(screen.getByLabelText("Prompt"), "Typing with 200 retained rows");
  await act(async () => { await Promise.resolve(); });
  assert.equal(calls.length, callsAfterPagination);
  assert.equal(document.querySelectorAll(".message-row").length, 200);
});

test("Home Console announces Codex readiness transitions through one persistent status", async () => {
  installFetch({ readinessState: "sign_in_required" });
  const user = userEvent.setup({ document: dom.window.document });
  render(<HomeConsole />);
  const prompt = await screen.findByLabelText("Prompt");
  await waitFor(() => assert.equal((prompt as HTMLTextAreaElement).disabled, false));
  const status = screen.getByRole("status");
  await user.click(screen.getByRole("button", { name: "Check readiness" }));
  await waitFor(() => assert.equal(
    status.textContent,
    "Run codex login in a terminal, complete the browser sign-in, then Recheck.",
  ));
  assert.equal((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled, true);
  assert.equal(screen.getByRole("button", { name: "Recheck" }).getAttribute("disabled"), null);
});
