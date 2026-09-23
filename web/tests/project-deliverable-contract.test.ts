import assert from "node:assert/strict";
import { test } from "node:test";
import { DeliverableContractError, deliverableRequest, deliverableResult } from "../src/lib/project-deliverable-contract.ts";

const projectId = "project_garage", versionId = `deliverable_version_${"a".repeat(32)}`, slotId = `deliverable_${"b".repeat(32)}`;
const layout = { width_mm: 6000, depth_mm: 5000, notes: "Bicycle access", openings: [{ edge: "south", offset_mm: 1300, width_mm: 2400, kind: "garage_door" }], placements: [{ id: "bench", kind: "workbench", label: "Workbench", x_mm: 3900, y_mm: 100, width_mm: 1600, depth_mm: 700 }] };
const publish = { project_id: projectId, slot: "layout", content: layout, expected_project_revision: 1, expected_slot_revision: 0, source_version_id: null, associated_task_id: null, expected_task_revision: null };
const version = { id: versionId, revision: 1, origin: "owner_edit", source_version_id: null, content: layout, created_at: 1790035200, preview_attachment_id: `attachment_${"c".repeat(32)}` };

test("exact owner layout requests and bounded projections retain only safe identities", () => {
  assert.deepEqual(deliverableRequest("publish", publish), publish);
  const result = deliverableResult("project", { project: { id: projectId, name: "Garage", revision: 1, status: "active" }, slots: [{ id: slotId, slot: "layout", head_revision: 1, versions: [version] }] }, { project_id: projectId });
  assert.equal(result.slots[0].versions[0].id, versionId);
  assert.deepEqual(deliverableResult("version", { ...version, project_id: projectId, slot: "layout" }, { project_id: projectId, version_id: versionId }).content, layout);
  assert.equal(deliverableResult("publish", { slot: "layout", slot_id: slotId, version_id: versionId, revision: 1, origin: "owner_edit", preview_attachment_id: version.preview_attachment_id }, publish).revision, 1);
});

test("widened requests, stale revisions and browser-canonicalized loopback links fail closed", () => {
  for (const value of [
    { ...publish, runtime_agent_ref: "default" },
    { ...publish, expected_slot_revision: true },
    { ...publish, content: { ...layout, width_mm: null } },
    { ...publish, content: { ...layout, placements: [{ ...layout.placements[0], kind: [] }] } },
  ]) assert.throws(() => deliverableRequest("publish", value), DeliverableContractError);
  for (const url of ["https://127.0.0.1/", "https://127.0.0.01/", "https://0x7f.0x0.0x0.0x1/", "javascript:alert(1)"]) {
    const value = { ...publish, slot: "products", content: { notes: "", items: [{ id: "shelf", name: "Shelf", quantity: 1, url, notes: "" }] } };
    assert.throws(() => deliverableRequest("publish", value), DeliverableContractError);
  }
  assert.throws(() => deliverableResult("project", { project: { id: projectId, name: "Garage", revision: 1, status: "active" }, slots: [{ id: slotId, slot: "layout", head_revision: 1, versions: [{ ...version, runtime_ref: "private" }] }] }, { project_id: projectId }), DeliverableContractError);
});

test("retired history and preview metadata stay exact and bounded", () => {
  const history = deliverableResult("retired-history", { versions: [{ id: versionId, project_id: projectId, slot: "layout", revision: 1, origin: "owner_edit", created_at: 1790035200 }], next_offset: null }, {});
  assert.equal(history.versions[0].id, versionId);
  assert.deepEqual(deliverableRequest("retired-history", { offset: 50 }), { offset: 50 });
  assert.throws(() => deliverableRequest("retired-history", { offset: 51 }), DeliverableContractError);
  const preview = deliverableResult("preview", { version_id: versionId, content_base64: "AQID", sha256: "a".repeat(64), byte_size: 3 }, { version_id: versionId });
  assert.equal(preview.byte_size, 3);
  assert.throws(() => deliverableResult("preview", { ...preview, byte_size: 3 * 1024 * 1024 }, { version_id: versionId }), DeliverableContractError);
});

test("review contracts bind an exact three-result preview and bounded owner decision", () => {
  const heads = (["layout", "products", "steps"] as const).map((slot, index) => ({ slot,
    version_id: `deliverable_version_${String(index + 1).repeat(32)}`, revision: 1, origin: "owner_edit" as const }));
  const request = { project_id: projectId, action: "request_changes", note: "Check shelf capacity.", affected_slots: ["products"] };
  assert.deepEqual(deliverableRequest("review-preview", request), request);
  const preview = { project_id: projectId, project_name: "Garage", project_revision: 1, action: "request_changes", note: request.note,
    affected_slots: ["products"], heads, confirmation_id: "f".repeat(64) };
  assert.equal(deliverableResult("review-preview", preview, request).heads.length, 3);
  const confirm = { ...request, confirmation_id: preview.confirmation_id };
  assert.deepEqual(deliverableRequest("review-confirm", confirm), confirm);
  const id = `deliverable_review_${"d".repeat(32)}`;
  assert.equal(deliverableResult("review-confirm", { id, revision: 1, action: request.action, project_id: projectId, duplicate: false }, confirm).id, id);
  assert.equal(deliverableResult("review-status", { project_id: projectId, project_name: "Garage", status: "request_changes",
    latest: { id, revision: 1, action: request.action, note: request.note, affected_slots: ["products"], created_at: 1790035200, current: true } }, { project_id: projectId }).status, "request_changes");
  for (const invalid of [
    { ...request, affected_slots: ["products", "layout"] },
    { ...request, affected_slots: [] },
    { ...request, note: "" },
    { ...request, source_run_id: "private" },
  ]) assert.throws(() => deliverableRequest("review-preview", invalid), DeliverableContractError);
  assert.throws(() => deliverableResult("review-preview", { ...preview, heads: [heads[0], heads[1], { ...heads[2], runtime_ref: "private" }] }, request), DeliverableContractError);
});
