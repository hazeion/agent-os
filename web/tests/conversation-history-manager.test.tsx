import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { JSDOM } from "jsdom";

const origin = "http://127.0.0.1:8890";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { pretendToBeVisual: true, url: origin });
for (const name of ["document", "HTMLElement", "KeyboardEvent", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) {
  Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
}
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });

const { act, cleanup, fireEvent, render, screen, waitFor } = await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { ConversationHistoryManager } = await import("../src/app/conversation-history-manager.tsx");

const timestamp = "2026-08-29T12:00:00Z";
const conversation = (id: string, title: string, state: "active" | "archived" = "active", revision = 1) => ({
  agent_id: "agent_history",
  archived_at: state === "archived" ? timestamp : null,
  created_at: timestamp,
  id,
  revision,
  state,
  title,
  title_source: "manual" as const,
  updated_at: timestamp,
});
const envelope = { runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" };
const history = (rows: ReturnType<typeof conversation>[]) => ({ ...envelope, conversations: rows, count: rows.length, next_cursor: null });

afterEach(() => cleanup());

test("history search rejects stale pages and changes selection only through Open", async () => {
  let resolveInitial: ((response: Response) => void) | null = null;
  const initial = new Promise<Response>((resolve) => { resolveInitial = resolve; });
  const opened: string[] = [];
  globalThis.fetch = async (input) => {
    const url = new URL(input instanceof Request ? input.url : input.toString(), origin);
    if (url.searchParams.get("q") === "fresh") return Response.json(history([conversation("conv_fresh", "Fresh result")]));
    return initial;
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ConversationHistoryManager initialConversations={[]} onChanged={() => undefined} onNotice={() => undefined} onOpen={(item) => opened.push(item.id)} />);
  await user.click(screen.getByText("Recent Conversations"));
  await user.type(screen.getByRole("searchbox", { name: "Search titles" }), "fresh");
  await screen.findByText("Fresh result");
  assert.deepEqual(opened, []);
  await act(async () => { resolveInitial?.(Response.json(history([conversation("conv_stale", "Stale result")]))); await initial; });
  assert.equal(screen.queryByText("Stale result"), null);
  await user.click(screen.getByRole("button", { name: "Open Fresh result, Conversation 1" }));
  assert.deepEqual(opened, ["conv_fresh"]);
});

test("history supports exact rename and reversible archive without Delete", async () => {
  let current = conversation("conv_manage", "Before rename");
  const changed: string[] = [];
  globalThis.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : input.toString(), origin);
    const method = init?.method ?? "GET";
    if (url.pathname === "/api/conversation-history" && method === "GET") {
      const query = (url.searchParams.get("q") ?? "").toLocaleLowerCase();
      const state = url.searchParams.get("state") ?? "all";
      const matches = (!query || current.title.toLocaleLowerCase().includes(query))
        && (state === "all" || current.state === state);
      return Response.json(history(matches ? [current] : []));
    }
    if (url.pathname.endsWith("/rename") && method === "POST") {
      const body = JSON.parse(String(init?.body));
      assert.deepEqual(body, { expected_revision: current.revision, title: "After rename" });
      current = { ...current, revision: current.revision + 1, title: body.title };
      return Response.json({ ...envelope, action: "rename", conversation: current });
    }
    if ((url.pathname.endsWith("/archive") || url.pathname.endsWith("/restore")) && method === "POST") {
      const archived = url.pathname.endsWith("/archive");
      current = { ...current, archived_at: archived ? timestamp : null, revision: current.revision + 1, state: archived ? "archived" : "active" };
      return Response.json({ ...envelope, action: archived ? "archive" : "restore", conversation: current });
    }
    throw new Error(`${method} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ConversationHistoryManager initialConversations={[current]} onChanged={(item) => changed.push(`${item.title}:${item.state}`)} onNotice={() => undefined} onOpen={() => undefined} />);
  await user.click(screen.getByText("Recent Conversations"));
  await screen.findByText("Before rename");
  assert.equal(screen.queryByRole("button", { name: /delete/iu }), null);
  const search = screen.getByRole("searchbox", { name: "Search titles" });
  await user.type(search, "Before rename");
  await user.click(screen.getByRole("button", { name: "Rename Before rename, Conversation 1" }));
  const input = screen.getByLabelText("Conversation title");
  await user.clear(input);
  await user.type(input, "After rename");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => assert.ok(changed.includes("After rename:active")));
  await waitFor(() => assert.equal(document.activeElement?.id, "conversation-history-search"));
  await user.clear(search);
  await screen.findByText("After rename");
  await user.selectOptions(screen.getByRole("combobox", { name: "Conversation history state" }), "active");
  await user.click(screen.getByRole("button", { name: "Archive After rename, Conversation 1" }));
  await waitFor(() => assert.ok(changed.includes("After rename:archived")));
  await waitFor(() => assert.equal(document.activeElement?.id, "conversation-history-search"));
  await user.selectOptions(screen.getByRole("combobox", { name: "Conversation history state" }), "archived");
  await user.click(screen.getByRole("button", { name: "Restore After rename, Conversation 1" }));
  await waitFor(() => assert.equal(changed.at(-1), "After rename:active"));
  await waitFor(() => assert.equal(document.activeElement?.id, "conversation-history-search"));
});

test("stale rename refreshes canonical history while preserving the proposed title", async () => {
  let current = conversation("conv_stale_rename", "Original title", "active", 1);
  let notice = "";
  globalThis.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : input.toString(), origin);
    const method = init?.method ?? "GET";
    if (url.pathname === "/api/conversation-history" && method === "GET") {
      const query = (url.searchParams.get("q") ?? "").toLocaleLowerCase();
      return Response.json(history(!query || current.title.toLocaleLowerCase().includes(query) ? [current] : []));
    }
    if (url.pathname.endsWith("/rename") && method === "POST") {
      current = { ...current, revision: 2, title: "Canonical newer title" };
      return Response.json({ schema_version: 1, status: "conflict" }, { status: 409 });
    }
    throw new Error(`${method} ${url.pathname}`);
  };
  const user = userEvent.setup({ document: dom.window.document });
  render(<ConversationHistoryManager initialConversations={[current]} onChanged={() => undefined} onNotice={(message) => { notice = message; }} onOpen={() => undefined} />);
  await user.click(screen.getByText("Recent Conversations"));
  await screen.findByText("Original title");
  const search = screen.getByRole("searchbox", { name: "Search titles" });
  await user.type(search, "Original");
  await user.click(screen.getByRole("button", { name: "Rename Original title, Conversation 1" }));
  const input = screen.getByLabelText("Conversation title") as HTMLInputElement;
  await user.clear(input);
  await user.type(input, "Proposed title");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => assert.equal(document.activeElement, search));
  assert.equal(input.value, "Proposed title");
  assert.match(notice, /kept for review/u);
  await user.clear(search);
  const retainedInput = await screen.findByLabelText("Conversation title") as HTMLInputElement;
  assert.equal(retainedInput.value, "Proposed title");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await screen.findByText("Canonical newer title");
});

test("closed history is keyboard reachable and multi-row actions have unique names", async () => {
  const rows = [
    conversation("conv_keyboard_a", "Repeated title"),
    conversation("conv_keyboard_b", "Repeated title"),
  ];
  globalThis.fetch = async () => Response.json(history(rows));
  const user = userEvent.setup({ document: dom.window.document });
  render(<ConversationHistoryManager initialConversations={rows} onChanged={() => undefined} onNotice={() => undefined} onOpen={() => undefined} />);
  await user.tab();
  const summary = screen.getByText("Recent Conversations");
  assert.equal(document.activeElement, summary);
  await user.keyboard("{Enter}");
  await screen.findByRole("searchbox", { name: "Search titles" });
  await user.tab();
  assert.equal(document.activeElement, screen.getByRole("searchbox", { name: "Search titles" }));
  assert.ok(screen.getByRole("button", { name: "Open Repeated title, Conversation 1" }));
  assert.ok(screen.getByRole("button", { name: "Open Repeated title, Conversation 2" }));
  assert.ok(screen.getByRole("button", { name: "Rename Repeated title, Conversation 1" }));
  assert.ok(screen.getByRole("button", { name: "Rename Repeated title, Conversation 2" }));
});

test("rename editor honors the 160 Unicode code-point boundary", async () => {
  const current = conversation("conv_unicode_title", "Original");
  globalThis.fetch = async () => Response.json(history([current]));
  const user = userEvent.setup({ document: dom.window.document });
  render(<ConversationHistoryManager initialConversations={[current]} onChanged={() => undefined} onNotice={() => undefined} onOpen={() => undefined} />);
  await user.click(screen.getByText("Recent Conversations"));
  await screen.findByText("Original");
  await user.click(screen.getByRole("button", { name: "Rename Original, Conversation 1" }));
  const input = screen.getByLabelText("Conversation title") as HTMLInputElement;
  fireEvent.change(input, { target: { value: "😀".repeat(160) } });
  assert.equal(Array.from(input.value).length, 160);
  assert.equal((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled, false);
  fireEvent.change(input, { target: { value: "😀".repeat(161) } });
  assert.equal(Array.from(input.value).length, 161);
  assert.equal((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled, true);
  fireEvent.change(input, { target: { value: "😀".repeat(162) } });
  assert.equal(Array.from(input.value).length, 161);
});
