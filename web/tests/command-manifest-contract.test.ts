import assert from "node:assert/strict";
import test from "node:test";

import {
  BridgeCommandManifestError,
  fetchBridgeCommandManifest,
} from "../src/lib/bridge-command-manifest.ts";
import { createCommandManifestHandler } from "../src/lib/command-manifest-route.ts";
import {
  parseCommandManifest,
  fetchCommandManifest,
  PublicCommandManifestError,
  type PublicCommandManifest,
} from "../src/lib/public-command-manifest.ts";

const environment = {
  MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49152",
  MENTAT_BRIDGE_TOKEN: "A_very_long_urlsafe_bridge_token_with_more_than_43_chars",
};
const manifest: PublicCommandManifest = {
  capabilities: {
    "commands.external_source": false,
    "commands.hermes_cli_passthrough": false,
    "commands.manifest.read": true,
  },
  commands: [
    {
      arguments: [{ description: "Optional active-provider model to select for review.", name: "model", required: false }],
      command: "/model",
      description: "Refresh current provider models",
      handler: "agent_console.refresh_models",
      safety: "read_only",
    },
    {
      arguments: [],
      command: "/new",
      description: "Start a new Hermes session",
      handler: "agent_console.new_session",
      safety: "local_state",
    },
    {
      arguments: [{ description: "Text guidance for the active remote Hermes run.", name: "guidance", required: true, variadic: true }],
      command: "/steer",
      description: "Guide the active remote Hermes run",
      handler: "agent_console.steer_active_run",
      safety: "remote_control",
    },
    {
      arguments: [],
      command: "/help",
      description: "Show dashboard commands",
      handler: "agent_console.show_help",
      safety: "read_only",
    },
  ],
  runtime: "python",
  schema_version: 1,
  service: "mentat-local-bridge",
  source: "mentat",
  status: "ready",
};

test("manifest parser accepts only the complete ordered version-one allowlist", () => {
  assert.deepEqual(parseCommandManifest(manifest), manifest);
  const nearMisses: unknown[] = [
    { ...manifest, commands: manifest.commands.slice(0, 3) },
    { ...manifest, commands: [...manifest.commands].reverse() },
    { ...manifest, commands: [...manifest.commands, { ...manifest.commands[3], command: "/unsafe" }] },
    { ...manifest, commands: manifest.commands.map((command, index) => index === 0 ? { ...command, handler: "agent_console.other" } : command) },
    { ...manifest, commands: manifest.commands.map((command, index) => index === 2 ? { ...command, safety: "read_only" } : command) },
    { ...manifest, cli_path: "/private/bin/hermes" },
  ];
  for (const value of nearMisses) {
    assert.throws(
      () => parseCommandManifest(value),
      (error: unknown) => error instanceof PublicCommandManifestError && error.code === "response_invalid",
    );
  }
});

test("manifest bridge uses one fixed private path and rejects private or partial responses", async () => {
  const calls: Array<{ headers: HeadersInit | undefined; url: string }> = [];
  const result = await fetchBridgeCommandManifest(async (input, init) => {
    calls.push({ headers: init?.headers, url: input.toString() });
    return Response.json(manifest);
  }, environment);
  assert.equal(result.commands.length, 4);
  assert.equal(calls[0]?.url, "http://127.0.0.1:49152/bridge/v1/agent-console/commands");
  assert.deepEqual(calls[0]?.headers, {
    Accept: "application/json",
    "X-Mentat-Bridge-Token": environment.MENTAT_BRIDGE_TOKEN,
  });
  for (const payload of [
    { ...manifest, runtime_reference: "private" },
    { ...manifest, commands: manifest.commands.slice(1) },
  ]) {
    await assert.rejects(
      fetchBridgeCommandManifest(async () => Response.json(payload), environment),
      (error: unknown) => error instanceof BridgeCommandManifestError && error.code === "bridge_response_invalid",
    );
  }
  await assert.rejects(
    fetchBridgeCommandManifest(
      async () => Response.json({
        runtime: "python",
        schema_version: 1,
        runtime_reference: "hidden",
        service: "mentat-local-bridge",
        status: "unavailable",
      }, { status: 503 }),
      environment,
    ),
    (error: unknown) => error instanceof BridgeCommandManifestError && error.code === "bridge_response_invalid",
  );
});

test("manifest route is same-origin, query-free, private, and fixed-error mapped", async () => {
  let calls = 0;
  const handler = createCommandManifestHandler({
    fetchManifest: async () => { calls += 1; return manifest; },
    gatewayPort: "8890",
  });
  const request = (suffix = "", origin = "http://127.0.0.1:8890") => new Request(`http://127.0.0.1:8890/api/agent-console/commands${suffix}`, {
    headers: { Host: "127.0.0.1:8890", Origin: origin, "Sec-Fetch-Site": "same-origin" },
  });
  const response = await handler(request());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.deepEqual(await response.json(), manifest);
  assert.equal((await handler(request("?source=cli"))).status, 400);
  assert.equal((await handler(request("", "https://attacker.example"))).status, 403);
  assert.equal(calls, 1);

  const unavailable = await createCommandManifestHandler({
    fetchManifest: async () => { throw new BridgeCommandManifestError("bridge_unavailable"); },
    gatewayPort: "8890",
  })(request());
  assert.equal(unavailable.status, 503);
  assert.deepEqual(await unavailable.json(), { schema_version: 1, status: "unavailable" });
});

test("public manifest client uses the fixed same-origin route and rejects near misses", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ credentials: RequestCredentials | undefined; url: string }> = [];
  globalThis.fetch = async (input, init) => {
    calls.push({ credentials: init?.credentials, url: input.toString() });
    return Response.json(manifest);
  };
  try {
    assert.deepEqual(await fetchCommandManifest(), manifest);
    assert.deepEqual(calls, [{ credentials: "same-origin", url: "/api/agent-console/commands" }]);
    globalThis.fetch = async () => Response.json({ ...manifest, commands: manifest.commands.slice(0, 3) });
    await assert.rejects(
      fetchCommandManifest(),
      (error: unknown) => error instanceof PublicCommandManifestError && error.code === "response_invalid",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
