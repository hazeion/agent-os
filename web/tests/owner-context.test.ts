import assert from "node:assert/strict";
import test from "node:test";
import { ownerBridgeHeaders, runWithOwnerContext } from "../src/lib/owner-request-context.ts";
import { fetchBridgeTasks } from "../src/lib/bridge-tasks.ts";

test("overlapping owner requests keep private bridge credentials isolated", async () => {
  const seen: Array<Record<string, string>> = [];
  let enter!: () => void;
  const wait = new Promise<void>(resolve => { enter = resolve; });
  const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:49001", MENTAT_BRIDGE_TOKEN: "T".repeat(43) };
  const fetcher = async (_url: string | URL | Request, init?: RequestInit) => {
    seen.push(Object.fromEntries(new Headers(init?.headers)));
    return Response.json({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", tasks: [], count: 0 });
  };
  await Promise.all([
    runWithOwnerContext({ cookie: "A".repeat(43), csrf: "B".repeat(43) }, async () => { await wait; await fetchBridgeTasks(fetcher, environment); }),
    runWithOwnerContext({ cookie: "C".repeat(43), csrf: null, lease: "D".repeat(32) }, async () => { await fetchBridgeTasks(fetcher, environment); enter(); }),
  ]);
  assert.equal(seen[0]!['x-mentat-owner-session'], "C".repeat(43));
  assert.equal(seen[0]!['x-mentat-owner-lease'], "D".repeat(32));
  assert.equal(seen[0]!['x-mentat-owner-csrf'], undefined);
  assert.equal(seen[1]!['x-mentat-owner-session'], "A".repeat(43));
  assert.equal(seen[1]!['x-mentat-owner-csrf'], "B".repeat(43));
  assert.equal(seen[1]!['x-mentat-owner-lease'], undefined);
  assert.deepEqual(ownerBridgeHeaders(), {});
});
