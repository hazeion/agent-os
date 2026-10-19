import assert from "node:assert/strict";
import test from "node:test";
import { inboxRequest, inboxResult, OwnerInboxContractError } from "../src/lib/owner-inbox-contract.ts";

const itemId = `inbox_item_${"a".repeat(32)}`;
const item = { id: itemId, kind: "result_review", revision: 1, created_at: 1790035200,
  unread: true, acknowledged: false, state: "needs_review", title: "Review Garage results" };
const envelope = (data: unknown) => ({ schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready", data });
const projectId = "project_garage";
const slots = (["layout", "products", "steps"] as const).map((slot, index) => ({
  id: `deliverable_${String(index + 1).repeat(32)}`, slot, head_revision: 1,
  versions: [{ id: `deliverable_version_${String(index + 1).repeat(32)}`, revision: 1, origin: "owner_edit", source_version_id: null,
    content: slot === "layout" ? { width_mm: 6000, depth_mm: 5000, notes: "Bike access", openings: [], placements: [] }
      : slot === "products" ? { notes: "Compare capacity", items: [] } : { notes: "Measure first", steps: [] },
    created_at: 1790035200, preview_attachment_id: slot === "layout" ? `attachment_${"a".repeat(32)}` : null }],
}));
const project = { project: { id: projectId, name: "Garage", revision: 1, status: "active" }, slots };
const review = { project_id: projectId, project_name: "Garage", status: "pending", latest: null };

test("Inbox contracts keep exact owner items and full current result content", () => {
  const page = inboxResult("page", envelope({ items: [item], next_cursor: null, counts: { needs_me: 1, unread: 1, all: 1 } }), { view: "needs_me", after: null });
  assert.equal(page.items[0].id, itemId);
  assert.equal(inboxResult("page", envelope({ items: [{ ...item, state: "stale" }], next_cursor: null, counts: { needs_me: 1, unread: 1, all: 1 } }), { view: "needs_me", after: null }).items[0].state, "stale");
  assert.throws(() => inboxResult("page", envelope({ items: [{ ...item, state: "resolved" }], next_cursor: null, counts: { needs_me: 1, unread: 1, all: 1 } }), { view: "needs_me", after: null }), OwnerInboxContractError);
  const opened = inboxResult("open", envelope({ item, project, review, versions: null }), { item_id: itemId });
  assert.equal(opened.project?.slots.length, 3);
  assert.deepEqual(inboxRequest("preview", { item_id: itemId, action: "accept", note: "", affected_slots: ["layout", "products", "steps"] }).affected_slots, ["layout", "products", "steps"]);
  assert.deepEqual(inboxResult("mark", envelope({ id: itemId, revision: 2, duplicate: false }), { item_id: itemId, action: "read", expected_revision: 1 }).revision, 2);
});

test("Inbox contracts reject widened authority, stale deep links, private identity and incomplete review", () => {
  for (const request of [
    { item_id: itemId, action: "approve", expected_revision: 1 },
    { item_id: itemId, action: "acknowledge", expected_revision: true },
    { item_id: itemId, action: "read", expected_revision: 1, project_id: projectId },
  ]) assert.throws(() => inboxRequest("mark", request), OwnerInboxContractError);
  assert.throws(() => inboxResult("page", envelope({ items: [{ ...item, source_incarnation: "private" }], next_cursor: null, counts: { needs_me: 1, unread: 1, all: 1 } }), { view: "needs_me", after: null }), OwnerInboxContractError);
  assert.throws(() => inboxResult("open", envelope({ item, project: { ...project, slots: slots.slice(0, 2) }, review, versions: null }), { item_id: itemId }), OwnerInboxContractError);
  assert.throws(() => inboxResult("open", envelope({ item, project, review: { ...review, status: "accept" }, versions: null }), { item_id: itemId }), OwnerInboxContractError);
  assert.throws(() => inboxResult("open", envelope({ item: { ...item, state: "resolved" }, project, review, versions: null }), { item_id: itemId }), OwnerInboxContractError);
});
