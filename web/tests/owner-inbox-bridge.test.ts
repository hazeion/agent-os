import assert from "node:assert/strict";
import test from "node:test";
import { ownerInboxCapability, OwnerInboxBridgeError } from "../src/lib/bridge-owner-inbox.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:43210", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready" };
const itemId = `inbox_item_${"b".repeat(32)}`;
const item = { id: itemId, kind: "result_review", revision: 1, created_at: 1790035200, unread: true,
  acknowledged: false, state: "needs_review", title: "Review Garage results" };

test("Inbox bridge uses one fixed owner-private page and mark transport", async () => {
  let calls = 0;
  const pageFetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls++;
    assert.equal(String(input), "http://127.0.0.1:43210/bridge/v1/owner-inbox/page?view=needs_me");
    assert.equal(init?.method, "GET");
    return Response.json({ ...envelope, data: { items: [item], next_cursor: null, counts: { needs_me: 1, unread: 1, all: 1 } } });
  };
  assert.equal((await ownerInboxCapability("page", { view: "needs_me", after: null }, pageFetcher, environment)).items[0].id, itemId);
  const mark = { item_id: itemId, action: "acknowledge", expected_revision: 1 };
  const markFetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls++;
    assert.equal(String(input), "http://127.0.0.1:43210/bridge/v1/owner-inbox/mark");
    assert.equal(init?.method, "POST");
    assert.deepEqual(JSON.parse(String(init?.body)), mark);
    return Response.json({ ...envelope, data: { id: itemId, revision: 2, duplicate: false } });
  };
  assert.equal((await ownerInboxCapability("mark", mark, markFetcher, environment)).revision, 2);
  await assert.rejects(() => ownerInboxCapability("mark", { ...mark, project_id: "project_garage" }, markFetcher, environment),
    (error: unknown) => error instanceof OwnerInboxBridgeError && error.status === 400);
  assert.equal(calls, 2);
});

test("Inbox bridge rejects private projection and preserves exact stale conflict", async () => {
  await assert.rejects(() => ownerInboxCapability("page", { view: "needs_me", after: null },
    async () => Response.json({ ...envelope, data: { items: [{ ...item, source_incarnation: "private" }], next_cursor: null,
      counts: { needs_me: 1, unread: 1, all: 1 } } }), environment),
  (error: unknown) => error instanceof OwnerInboxBridgeError && error.status === 502);
  await assert.rejects(() => ownerInboxCapability("open", { item_id: itemId },
    async () => Response.json({ schema_version: 1, status: "stale" }, { status: 409 }), environment),
  (error: unknown) => error instanceof OwnerInboxBridgeError && error.code === "stale" && error.status === 409);
});
