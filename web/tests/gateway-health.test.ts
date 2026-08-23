import assert from "node:assert/strict";
import test from "node:test";

import { GET } from "../src/app/api/gateway/health/route.ts";

test("gateway readiness is fixed, private, and independent of the Python bridge", async () => {
  const response = await GET();
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { gateway: "mentat-node-gateway", status: "ready" });
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.equal(response.headers.get("content-security-policy"), "default-src 'none'; frame-ancestors 'none'");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
});
