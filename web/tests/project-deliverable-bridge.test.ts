import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { DeliverableBridgeError, projectDeliverableCapability } from "../src/lib/bridge-project-deliverables.ts";

const environment = { MENTAT_BRIDGE_ORIGIN: "http://127.0.0.1:43210", MENTAT_BRIDGE_TOKEN: "a".repeat(43) };
const envelope = { schema_version: 1, service: "mentat-local-bridge", runtime: "python", status: "ready" };
const versionId = `deliverable_version_${"b".repeat(32)}`;
const publish = { project_id: "project_garage", slot: "steps", content: { notes: "", steps: [] }, expected_project_revision: 1, expected_slot_revision: 0, source_version_id: null, associated_task_id: null, expected_task_revision: null };

test("fixed bridge request carries only approved owner mutation and exact response", async () => {
  let calls = 0;
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    calls++;
    assert.equal(String(input), "http://127.0.0.1:43210/bridge/v1/project-deliverables/publish");
    assert.equal(init?.method, "POST");
    assert.equal(init?.headers && (init.headers as Record<string, string>)["X-Mentat-Bridge-Token"], environment.MENTAT_BRIDGE_TOKEN);
    assert.deepEqual(JSON.parse(String(init?.body)), publish);
    return Response.json({ ...envelope, data: { slot: "steps", slot_id: `deliverable_${"a".repeat(32)}`, version_id: versionId, revision: 1, origin: "owner_edit", preview_attachment_id: null } });
  };
  const result = await projectDeliverableCapability("publish", publish, fetcher, environment);
  assert.equal(result.version_id, versionId);
  assert.equal(calls, 1);
  await assert.rejects(() => projectDeliverableCapability("publish", { ...publish, runtime_agent_ref: "default" }, fetcher, environment), (error: unknown) => error instanceof DeliverableBridgeError && error.status === 400);
  assert.equal(calls, 1);
});

test("inbox capacity rejects a result save as one exact recoverable conflict", async () => {
  await assert.rejects(
    () => projectDeliverableCapability("publish", publish,
      async () => Response.json({ schema_version: 1, status: "inbox_capacity" }, { status: 409 }), environment),
    (error: unknown) => error instanceof DeliverableBridgeError && error.code === "inbox_capacity" && error.status === 409,
  );
});

test("preview must be one exact PNG with matching bytes and digest", async () => {
  const bytes = Buffer.from("89504e470d0a1a0a", "hex");
  const valid = { ...envelope, data: { version_id: versionId, content_base64: bytes.toString("base64"), sha256: createHash("sha256").update(bytes).digest("hex"), byte_size: bytes.length } };
  const fetcher = async () => Response.json(valid);
  assert.equal((await projectDeliverableCapability("preview", { version_id: versionId }, fetcher, environment)).byte_size, bytes.length);
  for (const data of [{ ...valid.data, sha256: "0".repeat(64) }, { ...valid.data, byte_size: bytes.length + 1 }, { ...valid.data, content_base64: Buffer.from("not a PNG").toString("base64"), sha256: createHash("sha256").update("not a PNG").digest("hex"), byte_size: 9 }]) {
    await assert.rejects(() => projectDeliverableCapability("preview", { version_id: versionId }, async () => Response.json({ ...valid, data }), environment), (error: unknown) => error instanceof DeliverableBridgeError && error.status === 502);
  }
});

test("fixed review confirmation returns only an exact owner decision", async () => {
  const request = { project_id: "project_garage", action: "accept", note: "", affected_slots: ["layout", "products", "steps"], confirmation_id: "f".repeat(64) };
  const decision = { id: `deliverable_review_${"d".repeat(32)}`, revision: 1, action: "accept", project_id: "project_garage", duplicate: false };
  const fetcher = async (input: string | URL | Request, init?: RequestInit) => {
    assert.equal(String(input), "http://127.0.0.1:43210/bridge/v1/project-deliverables/review-confirm");
    assert.equal(init?.method, "POST");
    assert.deepEqual(JSON.parse(String(init?.body)), request);
    return Response.json({ ...envelope, data: decision });
  };
  assert.deepEqual(await projectDeliverableCapability("review-confirm", request, fetcher, environment), decision);
  await assert.rejects(() => projectDeliverableCapability("review-confirm", request, async () => Response.json({ ...envelope, data: { ...decision, runtime_ref: "private" } }), environment),
    (error: unknown) => error instanceof DeliverableBridgeError && error.status === 502);
});
