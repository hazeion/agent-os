import assert from "node:assert/strict";
import test from "node:test";
import { BridgeTasksError, fetchBridgeTasks } from "../src/lib/bridge-tasks.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars" };
const task = { id: "task_1", title: "Current task", project: "Mentat", status: "todo", priority: "medium", due_date: null, tags: ["planning"], needs_attention: false, review_required: false, updated_at: "2026-08-22T00:00:00Z" };
const payload = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", tasks: [task], count: 1 };

test("Task bridge uses exactly one private path and rejects excluded fields", async () => {
  let url = "";
  await assert.rejects(fetchBridgeTasks(async (input) => { url = input.toString(); return Response.json({ ...payload, tasks: [{ ...task, description: "private" }] }); }, environment), BridgeTasksError);
  assert.equal(url, "http://127.0.0.1:49152/bridge/v1/tasks");
});

test("Task bridge returns only a copied bounded projection and maps fixed failure states", async () => {
  const result = await fetchBridgeTasks(async () => Response.json(payload), environment);
  assert.deepEqual(result, payload); assert.notEqual(result.tasks[0], task);
  const unavailable = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "unavailable" };
  await assert.rejects(fetchBridgeTasks(async () => Response.json(unavailable, { status: 503 }), environment), (error: unknown) => error instanceof BridgeTasksError && error.code === "bridge_unavailable");
  await assert.rejects(fetchBridgeTasks(async () => Response.json({ ...payload, count: 2 }), environment), (error: unknown) => error instanceof BridgeTasksError && error.code === "bridge_response_invalid");
  await assert.rejects(fetchBridgeTasks(async () => new Response("x".repeat(1_100_000), { headers: { "Content-Type": "application/json" } }), environment), (error: unknown) => error instanceof BridgeTasksError && error.code === "bridge_response_invalid");
  await assert.rejects(fetchBridgeTasks(async () => Response.json({ error: "bridge_route_not_found" }, { status: 404 }), environment), (error: unknown) => error instanceof BridgeTasksError && error.code === "bridge_unsupported");
});
