import assert from "node:assert/strict";
import test from "node:test";

import { GET } from "../src/app/api/runs/[runId]/events/route.ts";

const origin = "http://127.0.0.1:8890";
const context = { params: Promise.resolve({ runId: "run_route" }) };

test("selected Run event reconciliation rejects cross-site and foreign-origin GETs", async () => {
  const previousPort = process.env.PORT;
  process.env.PORT = "8890";
  try {
    const rejectedHeaders: Array<Record<string, string>> = [
      { Host: "127.0.0.1:8890", "Sec-Fetch-Site": "cross-site" },
      {
        Host: "127.0.0.1:8890",
        Origin: "https://attacker.example",
        "Sec-Fetch-Site": "same-origin",
      },
    ];
    for (const headers of rejectedHeaders) {
      const response = await GET(
        new Request(`${origin}/api/runs/run_route/events`, { headers }),
        context,
      );
      assert.equal(response.status, 403);
      assert.equal(await response.text(), "Forbidden\n");
      assert.equal(response.headers.get("cache-control"), "private, no-store");
    }
  } finally {
    if (previousPort === undefined) delete process.env.PORT;
    else process.env.PORT = previousPort;
  }
});

test("selected Run event reconciliation rejects query parameters before streaming", async () => {
  const previousPort = process.env.PORT;
  process.env.PORT = "8890";
  try {
    const response = await GET(
      new Request(`${origin}/api/runs/run_route/events?after=1`, {
        headers: { Host: "127.0.0.1:8890", "Sec-Fetch-Site": "same-origin" },
      }),
      context,
    );
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { schema_version: 1, status: "error" });
  } finally {
    if (previousPort === undefined) delete process.env.PORT;
    else process.env.PORT = previousPort;
  }
});
