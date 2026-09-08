import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
import { AgentSetupPanel } from "../src/app/agents/agent-setup-panel.tsx";
import { createAgentSetupHandler } from "../src/lib/agent-setup-route.ts";
import { requestBridgeAgentSetup } from "../src/lib/bridge-agent-setup.ts";

const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready" };
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "a".repeat(48) };
const agent = { id: "agent_new", name: "Research" };

test("Agent setup uses only fixed paths, exact name-only bodies and bounded safe results", async () => {
  let called = "";
  const read = await requestBridgeAgentSetup("check", {}, async (input) => { called = String(input); return Response.json({ ...envelope, state: "available", agent: null }); }, environment);
  assert.equal(called, "http://127.0.0.1:49152/bridge/v1/agent-setup/check");
  assert.ok("state" in read && read.state === "available");
  await assert.rejects(requestBridgeAgentSetup("preview", { name: "Research", runtime_agent_ref: "private" }, async () => { throw new Error("must not call"); }, environment));
  for (const value of [
    { ...envelope, state: "available", agent },
    { ...envelope, state: "already_configured", agent: { ...agent, runtime_agent_ref: "private" } },
    { ...envelope, state: "available", agent: null, token: "private" },
    { ...envelope, state: "unknown", agent: null },
    { ...envelope, state: ["available"], agent: null },
    { ...envelope, state: { value: "available" }, agent: null },
  ]) await assert.rejects(requestBridgeAgentSetup("check", {}, async () => Response.json(value), environment));
  await assert.rejects(requestBridgeAgentSetup("confirm", { name: "Research", confirmed: true, confirmation_id: "a".repeat(64) }, async () => Response.json({ ...envelope, agent: { ...agent, name: "Other" } }), environment));
  await assert.rejects(requestBridgeAgentSetup("check", {}, async () => new Response("x".repeat(4097), { headers: { "Content-Type": "application/json" } }), environment));
});

test("Agent setup routes reject foreign origins, queries, oversized and widened bodies before invocation", async () => {
  let calls = 0;
  const handler = createAgentSetupHandler("preview", { gatewayPort: "8888", execute: async () => { calls += 1; return { ...envelope, name: "Research", confirmation_id: "a".repeat(64) } as Awaited<ReturnType<typeof requestBridgeAgentSetup>>; } });
  const request = (body: string, origin = "http://127.0.0.1:8888", query = "") => new Request(`http://127.0.0.1:8888/api/agent-setup/preview${query}`, { method: "POST", headers: { Host: "127.0.0.1:8888", Origin: origin, "Content-Type": "application/json" }, body });
  assert.equal((await handler(request('{"name":"Research"}', "https://foreign.example"))).status, 403);
  for (const body of ['{"name":"Research","capabilities":["task.create"]}', '{"name":" padded"}', JSON.stringify({ name: "x".repeat(2000) }), '[]', '{}']) assert.equal((await handler(request(body))).status, 400);
  assert.equal((await handler(request('{"name":"Research"}', undefined, "?runtime=codex"))).status, 400);
  assert.equal(calls, 0);
  assert.equal((await handler(request('{"name":"Research"}'))).status, 200);
  assert.equal(calls, 1);
});

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://127.0.0.1:8888/agents", pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "HTMLInputElement", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "self", { configurable: true, value: dom.window });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { render, cleanup, screen, waitFor } = await import("@testing-library/react");
const { default: userEvent } = await import("@testing-library/user-event");
const { openAgentSetup } = await import(new URL("../public/agent-setup.js", import.meta.url).href);
afterEach(cleanup);

test("script-light Agent setup reviews before creation, invalidates edited names and refreshes canonical Agents", async () => {
  const calls: Array<{ action: string; body: Record<string, unknown> }> = []; let refreshed = 0;
  const fetcher = async (input: string, init: RequestInit) => {
    const action = input.split("/").at(-1)!; const body = JSON.parse(String(init.body)); calls.push({ action, body });
    if (action === "check") return Response.json({ ...envelope, state: "available", agent: null });
    if (action === "preview") return Response.json({ ...envelope, name: body.name, confirmation_id: "a".repeat(64) });
    return Response.json({ ...envelope, agent });
  };
  render(<AgentSetupPanel />); const user = userEvent.setup({ document: dom.window.document });
  assert.equal(calls.length, 0);
  await user.click(screen.getByRole("button", { name: "Create Agent / Setup" }));
  openAgentSetup(document.querySelector("[data-agent-setup-root]"), () => { refreshed += 1; }, fetcher);
  await waitFor(() => assert.equal((screen.getByLabelText("Agent name") as HTMLInputElement).disabled, false));
  await user.type(screen.getByLabelText("Agent name"), "Research");
  await user.click(screen.getByRole("button", { name: "Review Agent" }));
  await screen.findByRole("button", { name: "Confirm create Agent" });
  assert.equal(calls.some((call) => call.action === "confirm"), false);
  await user.type(screen.getByLabelText("Agent name"), " revised");
  assert.equal(screen.queryByRole("button", { name: "Confirm create Agent" }), null);
  await user.clear(screen.getByLabelText("Agent name")); await user.type(screen.getByLabelText("Agent name"), "Research");
  await user.click(screen.getByRole("button", { name: "Review Agent" }));
  await user.click(await screen.findByRole("button", { name: "Confirm create Agent" }));
  await screen.findByText("Agent creation verified. Open Home when you want to start a Conversation.");
  assert.equal(refreshed, 1);
  assert.deepEqual(calls.at(-1)?.body, { name: "Research", confirmation_id: "a".repeat(64), confirmed: true });
  assert.equal(calls.some((call) => /conversations|turns/.test(call.action)), false);
});

test("uncertain Agent creation requires Check setup and recovers the existing Agent without resubmitting", async () => {
  let confirms = 0; let committed = false;
  const fetcher = async (input: string) => {
    if (input.endsWith("/check")) return Response.json({ ...envelope, state: committed ? "already_configured" : "available", agent: committed ? agent : null });
    if (input.endsWith("/preview")) return Response.json({ ...envelope, name: "Research", confirmation_id: "b".repeat(64) });
    confirms += 1; committed = true; throw new Error("response lost after commit");
  };
  render(<AgentSetupPanel />); const user = userEvent.setup({ document: dom.window.document });
  openAgentSetup(document.querySelector("[data-agent-setup-root]"), () => undefined, fetcher);
  await waitFor(() => assert.equal((screen.getByLabelText("Agent name") as HTMLInputElement).disabled, false));
  await user.type(screen.getByLabelText("Agent name"), "Research");
  await user.click(screen.getByRole("button", { name: "Review Agent" }));
  await user.click(await screen.findByRole("button", { name: "Confirm create Agent" }));
  await screen.findByText(/Agent creation could not be verified/);
  assert.equal(screen.queryByRole("button", { name: "Confirm create Agent" }), null);
  await user.click(screen.getByRole("button", { name: "Check setup" }));
  await screen.findByText("Research is available in the canonical Agent registry.");
  assert.equal(confirms, 1);
});

test("native setup panel rejects non-string states and private Agent projections", async () => {
  for (const value of [{ state: ["available"], agent: null }, { state: { value: "available" }, agent: null }, { state: "already_configured", agent: { ...agent, runtime_agent_ref: "private" } }]) {
    render(<AgentSetupPanel />);
    openAgentSetup(document.querySelector("[data-agent-setup-root]"), () => undefined, async () => Response.json({ ...envelope, ...value }));
    await screen.findByText("Setup could not be verified. Check setup again when the local connection is available.");
    assert.equal(screen.queryByRole("button", { name: "Review Agent" }), null);
    cleanup();
  }
});
