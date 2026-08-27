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

const timestamp = "2026-08-26T12:00:00Z";
const agent = {
  capabilities: ["run.start"],
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
  targetConversation = conversation,
) {
  return {
    agent,
    conversation: targetConversation,
    current_run: currentRun,
    messages: [],
    next_message_cursor: null,
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
  };
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
  assert.equal(prompt.disabled, true);
  assert.equal(prompt.placeholder, "This Conversation has an active Run");
  assert.equal(
    screen.getByRole("status").textContent,
    "This Conversation already has an active Run. The draft was kept.",
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

test("Home Console disables composing for an active Run", async () => {
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
  await waitFor(() => assert.equal(prompt.disabled, true));
  assert.equal(prompt.placeholder, "This Conversation has an active Run");
  assert.equal((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled, true);
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
