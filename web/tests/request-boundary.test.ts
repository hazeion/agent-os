import assert from "node:assert/strict";
import test from "node:test";

import { evaluateRequestBoundary, parseGatewayPort } from "../src/lib/request-boundary.ts";

const baseRequest = {
  expectedPort: 8890,
  host: "127.0.0.1:8890",
  method: "GET",
  origin: null,
  secFetchSite: null,
};

test("the gateway accepts exact loopback navigation and same-origin requests", () => {
  assert.deepEqual(evaluateRequestBoundary(baseRequest), { allowed: true });
  assert.deepEqual(
    evaluateRequestBoundary({
      ...baseRequest,
      host: "localhost:8890",
      method: "POST",
      origin: "http://localhost:8890",
      secFetchSite: "same-origin",
    }),
    { allowed: true },
  );
});

test("foreign, malformed, and wrong-port Host values fail closed", () => {
  for (const host of [
    null,
    "attacker.example:8890",
    "127.0.0.1:8891",
    "user@127.0.0.1:8890",
    "127.0.0.1:8890/path",
  ]) {
    assert.equal(evaluateRequestBoundary({ ...baseRequest, host }).allowed, false, host ?? "null");
  }
});

test("unknown, malformed, cross-site, same-site, null, mismatched, and missing mutation origins fail closed", () => {
  const requests = [
    { ...baseRequest, secFetchSite: "cross-site" },
    { ...baseRequest, secFetchSite: "same-site" },
    { ...baseRequest, secFetchSite: "cross-site, same-origin" },
    { ...baseRequest, secFetchSite: "bogus" },
    { ...baseRequest, origin: "null" },
    { ...baseRequest, origin: "https://127.0.0.1:8890" },
    { ...baseRequest, origin: "http://127.0.0.1:8891" },
    { ...baseRequest, method: "POST" },
  ];
  for (const request of requests) {
    assert.equal(evaluateRequestBoundary(request).allowed, false, JSON.stringify(request));
  }
});

test("only absent, none, and same-origin fetch-site values are accepted", () => {
  for (const secFetchSite of [null, "none", "same-origin", " SAME-ORIGIN "]) {
    assert.deepEqual(
      evaluateRequestBoundary({ ...baseRequest, secFetchSite }),
      { allowed: true },
    );
  }
});

test("gateway port parsing remains bounded", () => {
  assert.equal(parseGatewayPort("8890"), 8890);
  for (const value of [undefined, "", "0", "65536", "not-a-port"]) {
    assert.equal(parseGatewayPort(value), 3000);
  }
});
