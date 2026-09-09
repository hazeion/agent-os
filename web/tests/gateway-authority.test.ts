import assert from "node:assert/strict";
import test from "node:test";

import {
  GatewayAuthorityStartupError,
  createGatewayAuthority,
  matchGatewayRoute,
  validateGatewayRouteManifest,
} from "../src/lib/gateway-authority.ts";
import type { GatewayRouteRule } from "../src/lib/gateway-route-manifest.ts";

const authority = createGatewayAuthority({ PORT: "8890" });

test("the process-owned authority captures local configuration and retains route bookkeeping", () => {
  assert.equal(authority.mode, "local");
  const decision = authority.authorize({
    host: "127.0.0.1:8890",
    method: "GET",
    origin: null,
    pathname: "/api/conversations/example",
    secFetchSite: null,
  });
  assert.equal(decision.allowed, true);
  assert.equal(decision.route?.path, "/api/conversations/[conversationId]");
  assert.equal(decision.route?.method, "GET");
  assert.equal(Object.isFrozen(authority), true);
});

test("manifested static surfaces include authored documents, finite assets, and framework chunks", () => {
  const decision = authority.authorize({
    host: "localhost:8890",
    method: "GET",
    origin: null,
    pathname: "/_next/static/chunks/app.js",
    secFetchSite: "same-origin",
  });
  assert.equal(decision.allowed, true);
  assert.equal(decision.route?.path, "/_next/static/[...path]");
  assert.equal(matchGatewayRoute("/", "GET")?.exposure, "static");
  assert.equal(matchGatewayRoute("/agents", "HEAD")?.source, "web/src/app/agents/page.tsx");
  assert.equal(matchGatewayRoute("/api/tasks", "HEAD")?.method, "GET");
  assert.equal(matchGatewayRoute("/api/tasks", "HEAD")?.path, "/api/tasks");
  assert.equal(matchGatewayRoute("/icon.svg", "GET")?.source, "web/src/app/icon.svg");
  assert.equal(matchGatewayRoute("/shell/agents.html", "GET")?.source, "web/scripts/prepare-standalone.mjs");
  assert.equal(matchGatewayRoute("/_next/static", "GET"), null);
  assert.equal(matchGatewayRoute("/favicon.ico", "GET"), null);
  assert.equal(matchGatewayRoute("/api/conversations/example", "DELETE"), null);
  assert.equal(matchGatewayRoute("/api/conversations/example/extra", "GET"), null);
});

test("the gateway selects the more literal operation and rejects equally-specific overlapping templates", () => {
  assert.equal(
    matchGatewayRoute("/api/conversations/example/context-packs/release", "POST")?.path,
    "/api/conversations/[conversationId]/context-packs/release",
  );
  const ambiguous = [
    { method: "GET", path: "/api/items/[first]" },
    { method: "GET", path: "/api/items/[second]" },
  ] as unknown as GatewayRouteRule[];
  assert.throws(() => validateGatewayRouteManifest(ambiguous), GatewayAuthorityStartupError);
  const ambiguousCatchall = [
    { method: "GET", path: "/shell/[...first]" },
    { method: "GET", path: "/shell/[...second]" },
  ] as unknown as GatewayRouteRule[];
  assert.throws(() => validateGatewayRouteManifest(ambiguousCatchall), GatewayAuthorityStartupError);
  const finiteShell = { method: "GET", path: "/shell/agents.html" } as unknown as GatewayRouteRule;
  const shellCatchall = { method: "GET", path: "/shell/[...path]" } as unknown as GatewayRouteRule;
  const optionalShellCatchall = { method: "GET", path: "/shell/[[...path]]" } as unknown as GatewayRouteRule;
  assert.equal(matchGatewayRoute("/shell/agents.html", "GET", [shellCatchall, finiteShell]), finiteShell);
  assert.equal(matchGatewayRoute("/shell", "GET", [optionalShellCatchall]), optionalShellCatchall);
});

test("unmatched paths retain Next fallback and native 404 behavior", () => {
  const decision = authority.authorize({
    host: "127.0.0.1:8890",
    method: "GET",
    origin: null,
    pathname: "/favicon.ico",
    secFetchSite: "same-origin",
  });
  assert.deepEqual(decision, { allowed: true, route: null });
});

test("the process-owned authority preserves local rejection decisions before route matching", () => {
  const decision = authority.authorize({
    host: "attacker.example:8890",
    method: "GET",
    origin: null,
    pathname: "/api/conversations",
    secFetchSite: null,
  });
  assert.deepEqual(decision, { allowed: false, reason: "host", route: null });
});

test("remote activation is rejected at startup and cannot be selected by request input", () => {
  assert.throws(() => createGatewayAuthority({ MENTAT_GATEWAY_MODE: "remote", PORT: "8890" }), GatewayAuthorityStartupError);
  assert.throws(() => createGatewayAuthority({ MENTAT_GATEWAY_MODE: "staging", PORT: "8890" }), GatewayAuthorityStartupError);
  const request = {
    host: "127.0.0.1:8890",
    method: "GET",
    mode: "remote",
    origin: null,
    pathname: "/",
    secFetchSite: null,
  };
  const decision = authority.authorize(request);
  assert.equal(decision.allowed, true);
  assert.equal(decision.route?.path, "/");
  assert.equal(decision.route?.exposure, "static");
  assert.equal(authority.mode, "local");
});
