import assert from "node:assert/strict";
import test from "node:test";

import { createGatewayHealthGetHandler } from "../src/app/api/gateway/health/route.ts";

function localRequest(path = "/api/gateway/health"): Request {
  return new Request(`http://127.0.0.1:8890${path}`, {
    headers: {
      Host: "127.0.0.1:8890",
      Origin: "http://127.0.0.1:8890",
      "Sec-Fetch-Site": "same-origin",
    },
  });
}

test("gateway readiness is fixed, private, and independent of the Python bridge", async () => {
  const response = await createGatewayHealthGetHandler({ gatewayPort: "8890" })(localRequest());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { gateway: "mentat-node-gateway", status: "ready" });
  assert.equal(response.headers.get("cache-control"), "private, no-store");
  assert.equal(response.headers.get("content-security-policy"), "default-src 'none'; frame-ancestors 'none'");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
});
