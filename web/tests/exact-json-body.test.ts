import assert from "node:assert/strict";
import test from "node:test";

import { hasExactEmptyJsonBody, readConfirmationId } from "../src/lib/exact-json-body.ts";

test("Run Stop preview accepts only its exact bounded JSON body", async () => {
  const request = (body: string, contentType = "application/json") => new Request("http://127.0.0.1:8890/api/runs/run_current/stop/preview", { method: "POST", headers: { "Content-Type": contentType }, body });
  assert.equal(await hasExactEmptyJsonBody(request("{}")), true);
  assert.equal(await hasExactEmptyJsonBody(request('{"extra":true}')), false);
  assert.equal(await hasExactEmptyJsonBody(request("{} ")), false);
  assert.equal(await hasExactEmptyJsonBody(request("{}", "text/plain")), false);
});

test("Run Stop confirmation has one bounded JSON field", async () => {
  const request = (body: string, contentType = "application/json") => new Request("http://127.0.0.1:8890/api/runs/run_current/stop", { method: "POST", headers: { "Content-Type": contentType }, body });
  const confirmationId = "a".repeat(64);
  assert.equal(await readConfirmationId(request(`{"confirmation_id":"${confirmationId}"}`)), confirmationId);
  assert.equal(await readConfirmationId(request(`{"confirmation_id":"${confirmationId}","extra":true}`)), null);
  assert.equal(await readConfirmationId(request("x".repeat(129))), null);
  assert.equal(await readConfirmationId(request(`{"confirmation_id":"${confirmationId}"}`, "text/plain")), null);
});
