import assert from "node:assert/strict";
import test from "node:test";

import { BridgeRunStopError, confirmBridgeRunStop, fetchBridgeRunStopPreview } from "../src/lib/bridge-run-stop.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars" };
const preview = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", action: "stop", run_id: "run_current", requires_confirmation: true, confirmation_id: "a".repeat(64) };
const result = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", action: "stop", run_id: "run_current", disposition: "requested" };

test("Run Stop bridge uses two fixed POST paths and exact bodies", async () => {
  const seen: Array<{ url: string; body: string | null }> = [];
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    seen.push({ url: input.toString(), body: typeof init?.body === "string" ? init.body : null });
    return Response.json(seen.length === 1 ? preview : result, { status: seen.length === 1 ? 200 : 202 });
  };
  assert.deepEqual(await fetchBridgeRunStopPreview("run_current", fetcher, environment), preview);
  assert.deepEqual(await confirmBridgeRunStop("run_current", preview.confirmation_id, fetcher, environment), result);
  assert.deepEqual(seen, [
    { url: "http://127.0.0.1:49152/bridge/v1/runs/run_current/stop/preview", body: "{}" },
    { url: "http://127.0.0.1:49152/bridge/v1/runs/run_current/stop", body: `{"confirmation_id":"${"a".repeat(64)}"}` },
  ]);
});

test("Run Stop bridge fails closed for invalid IDs, confirmations, and fixed failures", async () => {
  await assert.rejects(fetchBridgeRunStopPreview("run_invalid!", async () => Response.json(preview), environment), (error: unknown) => error instanceof BridgeRunStopError && error.code === "request_invalid");
  await assert.rejects(confirmBridgeRunStop("run_current", "short", async () => Response.json(result), environment), (error: unknown) => error instanceof BridgeRunStopError && error.code === "request_invalid");
  const conflict = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "conflict" };
  await assert.rejects(fetchBridgeRunStopPreview("run_current", async () => Response.json(conflict, { status: 409 }), environment), (error: unknown) => error instanceof BridgeRunStopError && error.code === "action_conflict");
  await assert.rejects(fetchBridgeRunStopPreview("run_current", async () => Response.json({ ...preview, runtime: "private" }), environment), BridgeRunStopError);
});
