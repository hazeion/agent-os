import assert from "node:assert/strict";
import test from "node:test";

import { BridgeAgentsError, fetchBridgeAgents } from "../src/lib/bridge-agents.ts";

const token = "A_very_long_urlsafe_bridge_token_with_more_than_43_chars";
const environment = {
  MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152",
  MENTAT_BRIDGE_TOKEN: token,
};
const agent = {
  capabilities: ["browser-use", "research.web"],
  id: "agent_researcher",
  name: "Researcher",
  runtime_config_id: "runtime_config_researcher",
  runtime_type: "hermes",
};
const validPayload = {
  agents: [agent],
  count: 1,
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  status: "ready",
};

test("Agent bridge fetch uses one fixed private path and removes unexpected fields", async () => {
  let receivedUrl = "";
  let receivedInit: RequestInit | undefined;
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    receivedUrl = input.toString();
    receivedInit = init;
    return Response.json({
      ...validPayload,
      agents: [{ ...agent, runtime_agent_ref: "private-canary" }],
    });
  };

  await assert.rejects(fetchBridgeAgents(fetcher, environment), BridgeAgentsError);
  assert.equal(receivedUrl, "http://127.0.0.1:49152/bridge/v1/agents");
  assert.equal((receivedInit?.headers as Record<string, string>)["X-Mentat-Bridge-Token"], token);
  assert.equal(receivedInit?.method, "GET");
});

test("Agent bridge returns a bounded canonical projection", async () => {
  const result = await fetchBridgeAgents(async () => Response.json(validPayload), environment);
  assert.deepEqual(result, validPayload);
  assert.notEqual(result.agents, validPayload.agents);
  assert.notEqual(result.agents[0], validPayload.agents[0]);
});

test("Agent bridge distinguishes unsupported and unavailable while malformed data fails closed", async () => {
  const unsupported = {
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "unsupported",
  };
  const unavailable = { ...unsupported, status: "unavailable" };
  const invalidResponses = [
    async () => Response.json({ ...validPayload, count: 2 }),
    async () => Response.json({ ...validPayload, agents: [{ ...agent, capabilities: ["z", "a"] }] }),
    async () => Response.json({ ...validPayload, private_path: "/private/canary" }),
    async () => Response.json({ ...validPayload, padding: "x".repeat(1_100_000) }),
    async () => new Response(JSON.stringify(validPayload), { headers: { "Content-Type": "text/plain" } }),
  ];
  for (const fetcher of invalidResponses) {
    await assert.rejects(fetchBridgeAgents(fetcher, environment), (error: unknown) => (
      error instanceof BridgeAgentsError && error.code === "bridge_response_invalid"
    ));
  }
  await assert.rejects(
    fetchBridgeAgents(async () => Response.json(unsupported, { status: 501 }), environment),
    (error: unknown) => error instanceof BridgeAgentsError && error.code === "bridge_unsupported",
  );
  await assert.rejects(
    fetchBridgeAgents(
      async () => Response.json({ error: "bridge_route_not_found" }, { status: 404 }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeAgentsError && error.code === "bridge_unsupported",
  );
  await assert.rejects(
    fetchBridgeAgents(async () => Response.json({ error: "other" }, { status: 404 }), environment),
    (error: unknown) => error instanceof BridgeAgentsError && error.code === "bridge_response_invalid",
  );
  await assert.rejects(
    fetchBridgeAgents(
      async () => Response.json({ error: "bridge_route_not_found", extra: "x" }, { status: 404 }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeAgentsError && error.code === "bridge_response_invalid",
  );
  await assert.rejects(
    fetchBridgeAgents(async () => Response.json(unavailable, { status: 503 }), environment),
    (error: unknown) => error instanceof BridgeAgentsError && error.code === "bridge_unavailable",
  );
});
