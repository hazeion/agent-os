import assert from "node:assert/strict";
import test from "node:test";

import { createAgentsGetHandler } from "../src/app/api/agents/route.ts";
import { createBridgeHealthGetHandler } from "../src/app/api/bridge/health/route.ts";
import { createProviderConnectionsGetHandler } from "../src/app/api/provider-connections/route.ts";
import { createRunsGetHandler } from "../src/app/api/runs/route.ts";
import { createTasksGetHandler } from "../src/app/api/tasks/route.ts";

const origin = "http://127.0.0.1:8890";

function localRequest(path: string): Request {
  return new Request(`${origin}${path}`, {
    headers: {
      Host: "127.0.0.1:8890",
      Origin: origin,
      "Sec-Fetch-Site": "same-origin",
    },
  });
}

test("simple read routes require their exact local manifest operation before calling the bridge", async () => {
  const calls: string[] = [];
  const agent = createAgentsGetHandler({ gatewayPort: "8890", fetchAgents: async () => {
    calls.push("agents");
    return { agents: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" };
  } });
  const tasks = createTasksGetHandler({ gatewayPort: "8890", fetchTasks: async () => {
    calls.push("tasks");
    return { tasks: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" };
  } });
  const runs = createRunsGetHandler({ gatewayPort: "8890", fetchRuns: async () => {
    calls.push("runs");
    return { runs: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" };
  } });
  const providers = createProviderConnectionsGetHandler({ gatewayPort: "8890", fetchConnections: async () => {
    calls.push("providers");
    return { connections: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" };
  } });
  const health = createBridgeHealthGetHandler({ gatewayPort: "8890", fetchHealth: async () => {
    calls.push("health");
    return { mentat_version: "1.0.0", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" };
  } });

  for (const [path, handler, projection] of [
    ["/api/agents", agent, { agents: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }],
    ["/api/tasks", tasks, { tasks: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }],
    ["/api/runs", runs, { runs: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }],
    ["/api/provider-connections", providers, { connections: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }],
  ] as const) {
    const response = await handler(localRequest(path));
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), projection);
    assert.equal(response.headers.get("cache-control"), "private, no-store");
  }

  const healthResponse = await health(localRequest("/api/bridge/health"));
  assert.equal(healthResponse.status, 200);
  assert.deepEqual(await healthResponse.json(), { gateway: "mentat-node-gateway", mentat_version: "1.0.0", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });

  assert.deepEqual(calls, ["agents", "tasks", "runs", "providers", "health"]);
});

test("simple read route validators reject query input and admission failures before bridge calls", async () => {
  let calls = 0;
  const handler = createTasksGetHandler({ gatewayPort: "8890", fetchTasks: async () => {
    calls += 1;
    return { tasks: [], count: 0, runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" };
  } });

  assert.equal((await handler(localRequest("/api/tasks?unexpected=value"))).status, 400);
  const response = await handler(new Request("http://localhost:8890/api/tasks", { headers: { Host: "attacker.example:8890" } }));
  assert.equal(response.status, 403);
  assert.equal(calls, 0);
});
