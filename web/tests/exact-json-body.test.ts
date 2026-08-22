import assert from "node:assert/strict";
import test from "node:test";

import { hasExactEmptyJsonBody, readConfirmationId, readMessageConfirmation, readMessagePreview, readRunResponsePreview, readRunResponseRouteBody } from "../src/lib/exact-json-body.ts";

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

test("Run message preview and confirmation accept only exact bounded text bodies", async () => {
  const preview = (body: string, contentType = "application/json") => new Request("http://127.0.0.1:8890/api/runs/run_current/message/preview", { method: "POST", headers: { "Content-Type": contentType }, body });
  const confirm = (body: string, contentType = "application/json") => new Request("http://127.0.0.1:8890/api/runs/run_current/message", { method: "POST", headers: { "Content-Type": contentType }, body });
  const confirmationId = "a".repeat(64);
  assert.equal(await readMessagePreview(preview('{"text":"Focus"}')), "Focus");
  assert.equal(await readMessagePreview(preview('{"text":"Focus","extra":true}')), null);
  assert.equal(await readMessagePreview(preview('{"text":"' + "x".repeat(6_001) + '"}')), null);
  const emojiMessage = "😀".repeat(6_000);
  assert.equal(await readMessagePreview(preview(JSON.stringify({ text: emojiMessage }))), emojiMessage);
  assert.equal(await readMessagePreview(preview(JSON.stringify({ text: emojiMessage + "😀" }))), null);
  assert.equal(await readMessagePreview(preview('{"text":"Focus"}', "text/plain")), null);
  assert.deepEqual(await readMessageConfirmation(confirm(`{"text":"Focus","confirmation_id":"${confirmationId}"}`)), { text: "Focus", confirmationId });
  assert.deepEqual(await readMessageConfirmation(confirm(JSON.stringify({ text: emojiMessage, confirmation_id: confirmationId }))), { text: emojiMessage, confirmationId });
  assert.equal(await readMessageConfirmation(confirm(`{"text":"Focus","confirmation_id":"${confirmationId}","extra":true}`)), null);
});

test("Run responses accept only request, preview, and confirmation shapes", async () => {
  const request = (body: string) => new Request("http://127.0.0.1:8890/api/runs/run_current/response", { method: "POST", headers: { "Content-Type": "application/json" }, body });
  const preview = (body: string) => new Request("http://127.0.0.1:8890/api/runs/run_current/response/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body });
  const confirmationId = "a".repeat(64);
  assert.equal(await readRunResponseRouteBody(request("{}")), "request");
  assert.deepEqual(await readRunResponsePreview(preview('{"response":{"kind":"approval","choice":"once"}}')), { kind: "approval", choice: "once" });
  assert.deepEqual(await readRunResponseRouteBody(request(`{"response":{"kind":"clarification","text":"Current project"},"confirmation_id":"${confirmationId}"}`)), { response: { kind: "clarification", text: "Current project" }, confirmationId });
  assert.equal(await readRunResponsePreview(preview('{"response":{"kind":"approval","choice":"once","extra":true}}')), null);
  assert.equal(await readRunResponseRouteBody(request('{"response":{"kind":"clarification","text":"x"}}')), null);
  const emojiText = "😀".repeat(2_000);
  assert.deepEqual(await readRunResponsePreview(preview(JSON.stringify({ response: { kind: "clarification", text: emojiText } }))), { kind: "clarification", text: emojiText });
});
