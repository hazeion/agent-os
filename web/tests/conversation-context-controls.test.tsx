import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { JSDOM } from "jsdom";
import { StrictMode } from "react";

const origin = "http://127.0.0.1:8890";
const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  pretendToBeVisual: true,
  url: origin,
});
for (const name of ["document", "HTMLElement", "MouseEvent", "Node", "navigator", "window"] as const) {
  Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
}
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });

const { cleanup, fireEvent, render, screen, waitFor } = await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { ConversationContextControls } = await import("../src/app/conversation-context-controls.tsx");
const { ConversationFileCard } = await import("../src/app/conversation-media.tsx");

const conversationId = "conv_media";
const revision = `sha256:${"b".repeat(64)}`;
const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready" };
const staged = {
  conversationId,
  attachments: [],
  contextPack: { id: "pack_0123456789abcdef", name: "Reviewed plan", revision },
  limits: { direct: 5 as const, total: 8 as const, images: 1 as const },
};
const cleared = { ...envelope, conversation_id: conversationId, attachments: [], context_pack: null, limits: { direct: 5, total: 8, images: 1 } };

afterEach(() => cleanup());

test("file controls require two explicit clicks before enabling a local Hermes Agent", async () => {
  const calls: Array<{ body: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    if ((init?.method ?? "GET") === "GET") return Response.json({ ...envelope, agent_id: "agent_local", state: "available" });
    calls.push({ body: String(init?.body ?? ""), path: input.toString() });
    return Response.json({
      ...envelope,
      agent: { capabilities: ["run.attachments", "run.start"], id: "agent_local", name: "Local Hermes", runtime_type: "hermes", system_role: null },
    });
  };
  let enabled: unknown = null;
  const user = userEvent.setup({ document: dom.window.document });
  render(<StrictMode><ConversationContextControls agent={{ capabilities: ["run.start"], id: "agent_local", name: "Local Hermes", runtime_type: "hermes", system_role: null }} conversationId={conversationId} disabledReason={null} onAgentEnabled={(agent) => { enabled = agent; }} onContext={() => undefined} onContextState={() => undefined} onNotice={() => undefined} onRefresh={() => undefined} staged={null} stagingState="ready" /></StrictMode>);

  await user.click(await screen.findByRole("button", { name: "Enable files" }));
  assert.equal(calls.length, 0);
  await user.click(screen.getByRole("button", { name: "Confirm enable files" }));
  await waitFor(() => assert.equal(calls.length, 1));
  assert.equal(calls[0].path, "/api/agents/agent_local/attachments/enable");
  assert.deepEqual(JSON.parse(calls[0].body), { expected_capabilities: ["run.start"] });
  assert.ok(enabled);
});

test("an instructions-only Context Pack has an exact release action", async () => {
  globalThis.fetch = async (input, init) => {
    assert.equal(input.toString(), `/api/conversations/${conversationId}/context-packs/release`);
    assert.equal(init?.body, "{}");
    return Response.json(cleared);
  };
  let context: unknown = null;
  const user = userEvent.setup({ document: dom.window.document });
  render(<ConversationContextControls agent={{ capabilities: ["run.attachments", "run.start"], id: "agent_local", name: "Local Hermes", runtime_type: "hermes", system_role: null }} conversationId={conversationId} disabledReason={null} onAgentEnabled={() => undefined} onContext={(value) => { context = value; }} onContextState={() => undefined} onNotice={() => undefined} onRefresh={() => undefined} staged={staged} stagingState="ready" />);

  await user.click(screen.getByRole("button", { name: "Remove Reviewed plan Context Pack" }));
  await waitFor(() => assert.deepEqual(context, { conversationId, attachments: [], contextPack: null, limits: { direct: 5, total: 8, images: 1 } }));
});

test("retained media cards expose only safe same-origin review and download links", () => {
  const url = `/api/conversations/${conversationId}/attachments/attachment_${"a".repeat(32)}/content`;
  render(<ConversationFileCard item={{ available: true, byteSize: 12, contentUrl: url, createdAt: null, expiresAt: null, id: `attachment_${"a".repeat(32)}`, kind: "text", mimeType: "text/plain", name: "result.txt", state: "attached" }} label="Generated file" />);

  assert.equal(screen.getByRole("link", { name: "Review" }).getAttribute("href"), url);
  assert.equal(screen.getByRole("link", { name: "Download" }).getAttribute("download"), "result.txt");
  assert.doesNotMatch(document.body.innerHTML, /storage_key|sha256|file:\/\//u);
});

test("a failed upload reconciles authority and keeps a filename-specific error chip", async () => {
  const calls: string[] = [];
  const oldItem = { available: true, byte_size: 3, created_at: "2026-08-29T01:02:03Z", expires_at: "2026-08-29T03:02:03Z", id: `attachment_${"d".repeat(32)}`, kind: "text", mime_type: "text/plain", name: "broken.txt", ordinal: 0, source: "upload", state: "staged" };
  const reconciled = { ...cleared, attachments: [oldItem] };
  globalThis.fetch = async (input, init) => {
    calls.push(`${init?.method ?? "GET"} ${input.toString()}`);
    if ((init?.method ?? "GET") === "POST") return Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 });
    return Response.json(reconciled);
  };
  const states: string[] = [];
  render(<ConversationContextControls agent={{ capabilities: ["run.attachments", "run.start"], id: "agent_local", name: "Local Hermes", runtime_type: "hermes", system_role: null }} conversationId={conversationId} disabledReason={null} onAgentEnabled={() => undefined} onContext={() => undefined} onContextState={(state) => states.push(state)} onNotice={() => undefined} onRefresh={() => undefined} staged={{ ...staged, contextPack: null, attachments: [{ available: true, byteSize: 3, contentUrl: `/api/conversations/${conversationId}/attachments/${oldItem.id}/content`, createdAt: oldItem.created_at, expiresAt: oldItem.expires_at, id: oldItem.id, kind: "text", mimeType: "text/plain", name: "broken.txt", ordinal: 0, source: "upload", state: "staged" }] }} stagingState="ready" />);

  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [new File(["broken"], "broken.txt", { type: "text/plain" })] } });

  await screen.findByRole("button", { name: "Dismiss failed upload broken.txt 1" });
  assert.match(screen.getByLabelText("Failed Conversation file uploads").textContent ?? "", /broken\.txt.*failed/u);
  assert.deepEqual(states, ["loading", "ready"]);
  assert.equal(calls.filter((call) => call.startsWith("GET")).length, 2);
});
