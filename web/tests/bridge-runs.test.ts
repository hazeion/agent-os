import assert from "node:assert/strict";
import test from "node:test";

import { BridgeRunsError, fetchBridgeRuns } from "../src/lib/bridge-runs.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars" };
const run = { id: "run_current", source: "task_dispatch", task_id: "task_1", agent_id: "agent_researcher", runtime_type: "hermes", status: "running", dispatch_state: "accepted", partial: false, timeline_truncated: false, created_at: "2026-08-22T00:00:00Z", updated_at: "2026-08-22T00:01:00Z", started_at: "2026-08-22T00:00:01Z", completed_at: null };
const payload = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", runs: [run], count: 1 };

test("Run bridge uses exactly one private path and rejects excluded fields", async () => {
  let url = "";
  await assert.rejects(fetchBridgeRuns(async (input) => { url = input.toString(); return Response.json({ ...payload, runs: [{ ...run, runtime_run_ref: "private" }] }); }, environment), BridgeRunsError);
  assert.equal(url, "http://127.0.0.1:49152/bridge/v1/runs");
});

test("Run bridge returns only a copied bounded projection and maps fixed failure states", async () => {
  const result = await fetchBridgeRuns(async () => Response.json(payload), environment);
  assert.deepEqual(result, payload); assert.notEqual(result.runs[0], run);
  const unavailable = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "unavailable" };
  await assert.rejects(fetchBridgeRuns(async () => Response.json(unavailable, { status: 503 }), environment), (error: unknown) => error instanceof BridgeRunsError && error.code === "bridge_unavailable");
  await assert.rejects(fetchBridgeRuns(async () => Response.json({ ...payload, count: 2 }), environment), (error: unknown) => error instanceof BridgeRunsError && error.code === "bridge_response_invalid");
  await assert.rejects(fetchBridgeRuns(async () => Response.json({ ...payload, unexpected: true }), environment), (error: unknown) => error instanceof BridgeRunsError && error.code === "bridge_response_invalid");
  await assert.rejects(fetchBridgeRuns(async () => Response.json({ ...payload, runs: [{ ...run, created_at: "not-a-timestamp" }] }), environment), (error: unknown) => error instanceof BridgeRunsError && error.code === "bridge_response_invalid");
  await assert.rejects(fetchBridgeRuns(async () => Response.json({ ...payload, runs: [{ ...run, created_at: "2026-08-22T00:00:00" }] }), environment), (error: unknown) => error instanceof BridgeRunsError && error.code === "bridge_response_invalid");
  await assert.rejects(fetchBridgeRuns(async () => new Response("x".repeat(1_100_000), { headers: { "Content-Type": "application/json" } }), environment), (error: unknown) => error instanceof BridgeRunsError && error.code === "bridge_response_invalid");
  await assert.rejects(fetchBridgeRuns(async () => Response.json({ error: "bridge_route_not_found" }, { status: 404 }), environment), (error: unknown) => error instanceof BridgeRunsError && error.code === "bridge_unsupported");
});
