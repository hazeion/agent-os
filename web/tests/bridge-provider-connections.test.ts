import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeProviderConnectionsError,
  fetchBridgeProviderConnections,
} from "../src/lib/bridge-provider-connections.ts";

const token = "A_very_long_urlsafe_bridge_token_with_more_than_43_chars";
const environment = {
  MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152",
  MENTAT_BRIDGE_TOKEN: token,
};
const connection = {
  capabilities: [
    { id: "ai.gateway", status: "credential_present" },
    { id: "sandbox.readiness", status: "needs_auth" },
    { id: "connect.token", status: "credential_present" },
  ],
  id: "connection_vercel",
  label: "Vercel",
  model: "openai/gpt-5.4",
  provider: "vercel",
  state: "configured",
};
const valid = {
  connections: [connection],
  count: 1,
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  status: "ready",
};

test("provider bridge uses one fixed private path and returns a detached safe projection", async () => {
  let receivedUrl = "";
  let receivedInit: RequestInit | undefined;
  const result = await fetchBridgeProviderConnections(async (input, init) => {
    receivedUrl = input.toString();
    receivedInit = init;
    return Response.json(valid);
  }, environment);

  assert.equal(receivedUrl, "http://127.0.0.1:49152/bridge/v1/provider-connections");
  assert.equal(receivedInit?.method, "GET");
  assert.equal(
    (receivedInit?.headers as Record<string, string>)["X-Mentat-Bridge-Token"],
    token,
  );
  assert.deepEqual(result, valid);
  assert.notEqual(result.connections, valid.connections);
  assert.notEqual(result.connections[0].capabilities, valid.connections[0].capabilities);
});

test("provider bridge rejects private fields and inconsistent capability state", async () => {
  const invalid = [
    { ...valid, connections: [{ ...connection, token: "secret-canary" }] },
    {
      ...valid,
      connections: [{
        ...connection,
        state: "needs_auth",
      }],
    },
    {
      ...valid,
      connections: [{
        ...connection,
        capabilities: [
          { id: "connect.token", status: "credential_present" },
          { id: "ai.gateway", status: "credential_present" },
        ],
      }],
    },
    { ...valid, count: 2 },
    { ...valid, private_path: "/private/canary" },
  ];
  for (const payload of invalid) {
    await assert.rejects(
      fetchBridgeProviderConnections(async () => Response.json(payload), environment),
      (error: unknown) => (
        error instanceof BridgeProviderConnectionsError
        && error.code === "bridge_response_invalid"
      ),
    );
  }
});

test("provider bridge maps only fixed unavailable and unsupported responses", async () => {
  const fixed = {
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "unsupported",
  };
  await assert.rejects(
    fetchBridgeProviderConnections(
      async () => Response.json(fixed, { status: 501 }),
      environment,
    ),
    (error: unknown) => (
      error instanceof BridgeProviderConnectionsError
      && error.code === "bridge_unsupported"
    ),
  );
  await assert.rejects(
    fetchBridgeProviderConnections(
      async () => Response.json({ ...fixed, status: "unavailable" }, { status: 503 }),
      environment,
    ),
    (error: unknown) => (
      error instanceof BridgeProviderConnectionsError
      && error.code === "bridge_unavailable"
    ),
  );
  await assert.rejects(
    fetchBridgeProviderConnections(
      async () => Response.json({ error: "bridge_route_not_found" }, { status: 404 }),
      environment,
    ),
    (error: unknown) => (
      error instanceof BridgeProviderConnectionsError
      && error.code === "bridge_unsupported"
    ),
  );
  await assert.rejects(
    fetchBridgeProviderConnections(
      async () => Response.json({ ...fixed, detail: "private" }, { status: 501 }),
      environment,
    ),
    (error: unknown) => (
      error instanceof BridgeProviderConnectionsError
      && error.code === "bridge_response_invalid"
    ),
  );
});

test("provider bridge bounds response bytes and requires JSON", async () => {
  await assert.rejects(
    fetchBridgeProviderConnections(
      async () => Response.json(valid, { headers: { "Content-Length": "70000" } }),
      environment,
    ),
    BridgeProviderConnectionsError,
  );
  await assert.rejects(
    fetchBridgeProviderConnections(
      async () => new Response(JSON.stringify(valid), { headers: { "Content-Type": "text/plain" } }),
      environment,
    ),
    BridgeProviderConnectionsError,
  );
});
