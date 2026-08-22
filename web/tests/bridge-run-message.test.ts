import assert from "node:assert/strict";
import test from "node:test";

import { BridgeRunMessageError, confirmBridgeRunMessage, previewBridgeRunMessage } from "../src/lib/bridge-run-message.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars" };
const preview = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", action: "message", run_id: "run_current", requires_confirmation: true, confirmation_id: "a".repeat(64) };
const result = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", action: "message", run_id: "run_current", disposition: "accepted" };

test("Run message bridge uses two fixed POST paths and exact bodies", async () => {
  const seen: Array<{ url: string; body: string | null }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    seen.push({ url: input.toString(), body: typeof init?.body === "string" ? init.body : null });
    return Response.json(seen.length === 1 ? preview : result, { status: seen.length === 1 ? 200 : 202 });
  };
  assert.deepEqual(await previewBridgeRunMessage("run_current", "Focus", fetcher, environment), preview);
  assert.deepEqual(await confirmBridgeRunMessage("run_current", "Focus", preview.confirmation_id, fetcher, environment), result);
  assert.deepEqual(seen, [
    { url: "http://127.0.0.1:49152/bridge/v1/runs/run_current/message/preview", body: '{"text":"Focus"}' },
    { url: "http://127.0.0.1:49152/bridge/v1/runs/run_current/message", body: `{"text":"Focus","confirmation_id":"${"a".repeat(64)}"}` },
  ]);
});

test("Run message bridge fails closed for invalid input and bridge failures", async () => {
  await assert.rejects(previewBridgeRunMessage("run_current", "", async () => Response.json(preview), environment), (error: unknown) => error instanceof BridgeRunMessageError && error.code === "request_invalid");
  await assert.rejects(previewBridgeRunMessage("run_current", "x".repeat(6_001), async () => Response.json(preview), environment), (error: unknown) => error instanceof BridgeRunMessageError && error.code === "request_invalid");
  await assert.doesNotReject(previewBridgeRunMessage("run_current", "😀".repeat(6_000), async () => Response.json(preview), environment));
  await assert.rejects(previewBridgeRunMessage("run_current", "😀".repeat(6_001), async () => Response.json(preview), environment), (error: unknown) => error instanceof BridgeRunMessageError && error.code === "request_invalid");
  const conflict = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "conflict" };
  await assert.rejects(previewBridgeRunMessage("run_current", "Focus", async () => Response.json(conflict, { status: 409 }), environment), (error: unknown) => error instanceof BridgeRunMessageError && error.code === "action_conflict");
  const failure = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "error" };
  await assert.rejects(previewBridgeRunMessage("run_current", "Focus", async () => Response.json(failure, { status: 500 }), environment), (error: unknown) => error instanceof BridgeRunMessageError && error.code === "action_failed");
});
