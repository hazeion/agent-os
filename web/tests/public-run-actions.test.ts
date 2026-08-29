import assert from "node:assert/strict";
import test from "node:test";

import {
  confirmRunResponse,
  confirmRunStop,
  fetchPendingRunRequest,
  previewRunResponse,
  previewRunStop,
  PublicRunActionError,
} from "../src/lib/public-run-actions.ts";

const request = { kind: "approval" as const, title: "Use a tool", summary: "Read project data", choices: [{ id: "once", label: "Allow once" }, { id: "deny", label: "Deny" }] };

test("public Run actions use exact same-origin bodies and reject private fields", async () => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ body: string; path: string }> = [];
  globalThis.fetch = async (input, init) => {
    const path = new URL(input.toString(), "http://127.0.0.1:8890").pathname;
    const body = String(init?.body);
    calls.push({ body, path });
    if (path.endsWith("/stop/preview")) return Response.json({ action: "stop", confirmation_id: "a".repeat(64), requires_confirmation: true, run_id: "run_public", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    if (path.endsWith("/stop")) return Response.json({ action: "stop", disposition: "requested", run_id: "run_public", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }, { status: 202 });
    if (path.endsWith("/response/preview")) return Response.json({ action: "respond", confirmation_id: "b".repeat(64), request, requires_confirmation: true, run_id: "run_public", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    if (path.endsWith("/response") && body === "{}") return Response.json({ action: "respond", request, requires_confirmation: false, run_id: "run_public", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
    return Response.json({ action: "respond", disposition: "accepted", run_id: "run_public", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" }, { status: 202 });
  };
  try {
    assert.equal((await fetchPendingRunRequest("run_public")).kind, "approval");
    const responsePreview = await previewRunResponse("run_public", { kind: "approval", choice: "once" });
    await confirmRunResponse("run_public", { kind: "approval", choice: "once" }, responsePreview.confirmation_id);
    const stopPreview = await previewRunStop("run_public");
    await confirmRunStop("run_public", stopPreview.confirmation_id);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(calls.map((call) => call.path), [
    "/api/runs/run_public/response",
    "/api/runs/run_public/response/preview",
    "/api/runs/run_public/response",
    "/api/runs/run_public/stop/preview",
    "/api/runs/run_public/stop",
  ]);

  globalThis.fetch = async () => Response.json({ action: "stop", confirmation_id: "a".repeat(64), private_runtime_ref: "forbidden", requires_confirmation: true, run_id: "run_public", runtime: "python", schema_version: 1, service: "mentat-local-bridge", status: "ready" });
  try {
    await assert.rejects(
      previewRunStop("run_public"),
      (error: unknown) => error instanceof PublicRunActionError && error.code === "response_invalid",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
