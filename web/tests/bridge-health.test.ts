import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeHealthError,
  fetchBridgeHealth,
  loadBridgeConfiguration,
} from "../src/lib/bridge-health.ts";

const token = "A_very_long_urlsafe_bridge_token_with_more_than_43_chars";
const environment = {
  MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152",
  MENTAT_BRIDGE_TOKEN: token,
};
const validPayload = {
  mentat_version: "v0.1.0-beta.1",
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  status: "ready",
};

test("bridge configuration requires a fixed numeric loopback origin and URL-safe token", () => {
  assert.deepEqual(loadBridgeConfiguration(environment), {
    origin: "http://127.0.0.1:49152",
    token,
  });
  assert.deepEqual(
    loadBridgeConfiguration({
      ...environment,
      MENTAT_BRIDGE_ORIGIN: "http://[::1]:49152",
    }),
    { origin: "http://[::1]:49152", token },
  );
  for (const candidate of [
    { ...environment, MENTAT_BRIDGE_ORIGIN: "http://localhost:49152" },
    { ...environment, MENTAT_BRIDGE_ORIGIN: "http://0.0.0.0:49152" },
    { ...environment, MENTAT_BRIDGE_ORIGIN: "https://127.0.0.1:49152" },
    { ...environment, MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152/path" },
    { ...environment, MENTAT_BRIDGE_TOKEN: "short" },
  ]) {
    assert.throws(() => loadBridgeConfiguration(candidate), BridgeHealthError);
  }
});

test("bridge fetch constructs one fixed private request and returns a redacted projection", async () => {
  let receivedUrl = "";
  let receivedInit: RequestInit | undefined;
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    receivedUrl = input.toString();
    receivedInit = init;
    return Response.json({ ...validPayload, private_path: "/private/operator" });
  };

  const result = await fetchBridgeHealth(fetcher, environment);
  assert.equal(receivedUrl, "http://127.0.0.1:49152/bridge/v1/health");
  assert.equal((receivedInit?.headers as Record<string, string>)["X-Mentat-Bridge-Token"], token);
  assert.equal(receivedInit?.method, "GET");
  assert.deepEqual(result, validPayload);
  assert.equal("private_path" in result, false);
});

test("invalid status, schema, content type, payload size, and transport fail closed", async () => {
  const responses = [
    async () => Response.json(validPayload, { status: 503 }),
    async () => Response.json({ ...validPayload, schema_version: 2 }),
    async () => new Response(JSON.stringify(validPayload), { headers: { "Content-Type": "text/plain" } }),
    async () => Response.json({ ...validPayload, padding: "x".repeat(5000) }),
    async () => new Response(JSON.stringify(validPayload), {
      headers: {
        "Content-Length": "5000",
        "Content-Type": "application/json",
      },
    }),
    async () => new Response(new Uint8Array([0xff, 0xfe]), {
      headers: { "Content-Type": "application/json" },
    }),
    async () => { throw new Error("private transport detail"); },
  ];
  for (const fetcher of responses) {
    await assert.rejects(fetchBridgeHealth(fetcher, environment), BridgeHealthError);
  }
});
