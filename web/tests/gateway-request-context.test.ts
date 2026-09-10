import assert from "node:assert/strict";
import test from "node:test";

import { createGatewayAuthority, type GatewayAuthority } from "../src/lib/gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "../src/lib/gateway-route-manifest.ts";
import { withGatewayRoute } from "../src/lib/gateway-request-context.ts";

const conversationsGet = route("GET", "/api/conversations");
const conversationsPost = route("POST", "/api/conversations");

function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const match = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!match) throw new Error(`missing test manifest route: ${method} ${path}`);
  return match;
}

function authorityFor(routeDecision: GatewayRouteRule | null, allowed = true): Pick<GatewayAuthority, "authorize"> {
  return {
    authorize() {
      return allowed ? { allowed: true, route: routeDecision } : { allowed: false, reason: "host", route: null };
    },
  };
}

function localRequest(method = "GET", path = "/api/conversations"): Request {
  return new Request(`http://127.0.0.1:8890${path}`, {
    headers: {
      Host: "127.0.0.1:8890",
      Origin: "http://127.0.0.1:8890",
      "Sec-Fetch-Site": "same-origin",
    },
    method,
  });
}

test("gateway wrapper rejects denied, unmatched, and operation-mismatched requests before validation", async () => {
  for (const authority of [
    authorityFor(null, false),
    authorityFor(null),
    authorityFor(conversationsPost),
  ]) {
    let validatorCalls = 0;
    let handlerCalls = 0;
    const handler = withGatewayRoute(conversationsGet, {
      authority,
      handler: async () => {
        handlerCalls += 1;
        return new Response("unexpected");
      },
      validator: {
        validate: async () => {
          validatorCalls += 1;
          return { parsed: true };
        },
      },
    });

    const response = await handler(localRequest());
    assert.equal(response.status, 403);
    assert.equal(await response.text(), "Forbidden\n");
    assert.equal(validatorCalls, 0);
    assert.equal(handlerCalls, 0);
  }
});

test("gateway wrapper rejects a known route when its request method selects a different operation", async () => {
  let validatorCalls = 0;
  let handlerCalls = 0;
  const handler = withGatewayRoute(conversationsGet, {
    authority: createGatewayAuthority({ PORT: "8890" }),
    handler: async () => {
      handlerCalls += 1;
      return new Response("unexpected");
    },
    validator: {
      validate: async () => {
        validatorCalls += 1;
        return null;
      },
    },
  });

  const response = await handler(localRequest("POST"));
  assert.equal(response.status, 403);
  assert.equal(validatorCalls, 0);
  assert.equal(handlerCalls, 0);
});

test("gateway wrapper preserves Next implicit HEAD dispatch to an exact GET operation", async () => {
  const getRule = GATEWAY_ROUTE_MANIFEST.find((rule) => rule.method === "GET" && rule.path === "/api/tasks")!;
  let validated = 0;
  let handled = 0;
  const wrapped = withGatewayRoute<boolean>(getRule, {
    authority: createGatewayAuthority({ PORT: "8890" }),
    validator: { validate() { validated += 1; return true; } },
    handler: ({ value }) => { handled += 1; return new Response(value ? "ok" : "bad"); },
  });
  const response = await wrapped(localRequest("HEAD", "/api/tasks"));
  assert.equal(response.status, 200);
  assert.equal(validated, 1);
  assert.equal(handled, 1);
});

test("a static wrapper accepts Next's unused route context without exposing it to validation or its handler", async () => {
  const handler = withGatewayRoute(conversationsGet, {
    authority: authorityFor(conversationsGet),
    handler: async (context) => {
      assert.deepEqual(context, { rule: conversationsGet, value: true });
      return new Response("ok");
    },
    validator: { validate: () => true },
  });

  const response = await handler(localRequest(), { params: Promise.resolve({}) });
  assert.equal(await response.text(), "ok");
});

test("gateway wrapper projects dynamic params through validation without exposing the Next context to its handler", async () => {
  const handler = withGatewayRoute<{ conversationId: string; page: number }, { params: Promise<{ conversationId: string }> }>(conversationsGet, {
    authority: authorityFor(conversationsGet),
    handler: async (context) => {
      assert.deepEqual(context, { rule: conversationsGet, value: { conversationId: "conversation_1", page: 1 } });
      assert.equal(Object.isFrozen(context), true);
      assert.equal(Object.isFrozen(context.rule), true);
      return Response.json({ status: "ok" });
    },
    validator: {
      validate: async (_request, context, nextContext) => {
        assert.deepEqual(context, { rule: conversationsGet });
        assert.equal(Object.isFrozen(context), true);
        const { conversationId } = await nextContext.params;
        return { conversationId, page: 1 };
      },
    },
  });

  const response = await handler(localRequest(), { params: Promise.resolve({ conversationId: "conversation_1" }) });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ok" });
});
