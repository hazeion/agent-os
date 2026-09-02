import assert from "node:assert/strict";
import test from "node:test";

import { BridgePlanningError } from "../src/lib/bridge-planning.ts";
import { fetchBridgePlanningSearch } from "../src/lib/bridge-planning-search.ts";
import { createPlanningSearchHandler } from "../src/lib/planning-search-route.ts";
import { parsePlanningSearch, PublicPlanningSearchError, readPlanningSearch } from "../src/lib/public-planning-search.ts";

const envelope = { runtime: "python" as const, schema_version: 1 as const, service: "mentat-local-bridge" as const, status: "ready" as const };
const result = { ...envelope, project_count: 1, projects: [{ id: "project_alpha", title: "Alpha", type: "project" as const }], query: "Alpha", task_count: 1, tasks: [{ id: "task_alpha", title: "Ship Alpha", type: "task" as const }], truncated: false };
const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152", MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars" };
const headers = { Host: "127.0.0.1:8890", Origin: "http://127.0.0.1:8890", "Sec-Fetch-Site": "same-origin" };

test("planning search accepts only the narrow detached title-and-id projection", () => {
  assert.deepEqual(parsePlanningSearch(result, "Alpha"), result);
  assert.throws(() => parsePlanningSearch({ ...result, private_path: "C:/private" }), PublicPlanningSearchError);
  assert.throws(() => parsePlanningSearch({ ...result, tasks: [{ ...result.tasks[0], title: "" }] }), PublicPlanningSearchError);
  assert.throws(() => parsePlanningSearch({ ...result, project_count: 2 }), PublicPlanningSearchError);
  assert.throws(() => parsePlanningSearch({ ...result, query: "Other" }, "Alpha"), PublicPlanningSearchError);
});

test("planning search bridge uses one fixed loopback GET, exact query, and bounded caller cancellation", async () => {
  let path = "";
  const actual = await fetchBridgePlanningSearch("Alpha", async (input, init) => {
    path = input.toString();
    assert.equal(init?.method, "GET");
    return Response.json(result);
  }, environment);
  assert.deepEqual(actual, result);
  assert.equal(path, "http://127.0.0.1:49152/bridge/v1/agent-console/planning-search?q=Alpha");
  const controller = new AbortController(); let bridgeSignal: AbortSignal | undefined;
  await fetchBridgePlanningSearch("Alpha", async (_input, init) => { bridgeSignal = init?.signal ?? undefined; return Response.json(result); }, environment, controller.signal);
  assert.notEqual(bridgeSignal, controller.signal); assert.equal(bridgeSignal?.aborted, false); controller.abort(); assert.equal(bridgeSignal?.aborted, true);
  await assert.rejects(fetchBridgePlanningSearch(" Alpha", async () => Response.json(result), environment), BridgePlanningError);
  await assert.rejects(fetchBridgePlanningSearch("Alpha", async () => Response.json({ ...result, tasks: [] }), environment), BridgePlanningError);
});

test("planning search Next route is same-origin, forwards cancellation, and accepts only one exact q parameter", async () => {
  const queries: string[] = []; let receivedSignal: AbortSignal | undefined;
  const handler = createPlanningSearchHandler({ gatewayPort: "8890", search: async (query, signal) => { queries.push(query); receivedSignal = signal; return result; } });
  const good = await handler(new Request("http://127.0.0.1:8890/api/agent-console/planning-search?q=Alpha", { headers }));
  assert.equal(good.status, 200); assert.deepEqual(await good.json(), result); assert.deepEqual(queries, ["Alpha"]); assert.ok(receivedSignal);
  assert.equal((await handler(new Request("http://127.0.0.1:8890/api/agent-console/planning-search?q=Alpha&q=Beta", { headers })).then((response) => response.status)), 400);
  assert.equal((await handler(new Request("http://127.0.0.1:8890/api/agent-console/planning-search?q=Alpha", { headers: { ...headers, Origin: "http://evil.test", "Sec-Fetch-Site": "cross-site" } })).then((response) => response.status)), 403);
});

test("public planning search client uses only the named same-origin route", async () => {
  const original = globalThis.fetch; let path = "";
  globalThis.fetch = async (input) => { path = input.toString(); return Response.json(result); };
  try {
    assert.deepEqual(await readPlanningSearch("Alpha"), result);
    assert.equal(path, "/api/agent-console/planning-search?q=Alpha");
  } finally { globalThis.fetch = original; }
});
