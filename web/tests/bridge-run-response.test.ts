import assert from "node:assert/strict";
import test from "node:test";

import { BridgeRunResponseError, confirmBridgeRunResponse, fetchBridgeRunResponseRequest, previewBridgeRunResponse } from "../src/lib/bridge-run-response.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152/", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const request = { kind: "approval", title: "Use a tool", summary: "Read project data", choices: [{ id: "once", label: "Allow once" }, { id: "deny", label: "Deny" }] } as const;
const pending = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", action: "respond", run_id: "run_current", request, requires_confirmation: false } as const;
const preview = { ...pending, requires_confirmation: true, confirmation_id: "a".repeat(64) } as const;
const accepted = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", action: "respond", run_id: "run_current", disposition: "accepted" } as const;

test("Run response bridge uses only fixed request, preview, and confirmation bodies", async () => {
  const calls: Array<{ url: string; body: string }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), body: String(init?.body) });
    const value = calls.length === 1 ? pending : calls.length === 2 ? preview : accepted;
    return new Response(JSON.stringify(value), { status: calls.length === 3 ? 202 : 200, headers: { "content-type": "application/json", "content-length": String(JSON.stringify(value).length) } });
  };
  await fetchBridgeRunResponseRequest("run_current", fetcher, environment);
  await previewBridgeRunResponse("run_current", { kind: "approval", choice: "once" }, fetcher, environment);
  await confirmBridgeRunResponse("run_current", { kind: "approval", choice: "once" }, "a".repeat(64), fetcher, environment);
  assert.deepEqual(calls, [
    { url: "http://127.0.0.1:49152/bridge/v1/runs/run_current/response", body: "{}" },
    { url: "http://127.0.0.1:49152/bridge/v1/runs/run_current/response/preview", body: '{"response":{"kind":"approval","choice":"once"}}' },
    { url: "http://127.0.0.1:49152/bridge/v1/runs/run_current/response", body: `{"response":{"kind":"approval","choice":"once"},"confirmation_id":"${"a".repeat(64)}"}` },
  ]);
});

test("Run response bridge rejects malformed actions and fixed bridge failures", async () => {
  await assert.rejects(() => previewBridgeRunResponse("run_current", { kind: "approval", choice: "deny", extra: "no" } as never, async () => new Response(), environment), (error: unknown) => error instanceof BridgeRunResponseError && error.code === "request_invalid");
  await assert.rejects(() => fetchBridgeRunResponseRequest("run_current", async () => new Response(JSON.stringify({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "unsupported" }), { status: 501, headers: { "content-type": "application/json" } }), environment), (error: unknown) => error instanceof BridgeRunResponseError && error.code === "action_unsupported");
  await assert.rejects(() => confirmBridgeRunResponse("run_current", { kind: "approval", choice: "once" }, "a".repeat(64), async () => new Response(JSON.stringify({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "partial" }), { status: 500, headers: { "content-type": "application/json" } }), environment), (error: unknown) => error instanceof BridgeRunResponseError && error.code === "action_partial");
});
