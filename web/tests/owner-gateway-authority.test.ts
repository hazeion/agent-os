import assert from "node:assert/strict";
import test from "node:test";
import { createGatewayAuthority } from "../src/lib/gateway-authority.ts";
import { ownerCookie, sessionContext, OWNER_COOKIE, OWNER_CSRF_COOKIE } from "../src/lib/owner-cookies.ts";

const authority = createGatewayAuthority({ PORT: "8888", MENTAT_GATEWAY_MODE: "owner", MENTAT_OWNER_ORIGIN: "https://mentat.example" });
const request = { host: "mentat.example", pathname: "/", method: "GET", origin: null, secFetchSite: null, forwardedHost: "mentat.example", forwardedProto: "https", forwardedFor: "127.0.0.1", forwardedPort: "8888" };

test("owner mode separates authenticated documents, public login and bounded assets", () => {
  assert.equal(authority.authorize(request).route?.exposure, "owner_session");
  assert.equal(authority.authorize({ ...request, pathname: "/sign-in" }).route?.exposure, "anonymous_auth");
  assert.equal(authority.authorize({ ...request, pathname: "/_next/static/app.js" }).route?.exposure, "static");
  assert.equal(authority.authorize({ ...request, pathname: "/unknown" }).allowed, false);
  assert.equal(authority.authorize({ ...request, pathname: "/api/gateway/health" }).allowed, false);
});

test("owner mode requires exact proxy host/protocol and origin for unsafe requests", () => {
  for (const change of [{ host: "evil.example" }, { forwardedHost: "evil.example" }, { forwardedProto: "http" }, { forbiddenForwarding: true }, { forwardedFor: "127.0.0.1, evil" }, { forwardedPort: "443" }, { secFetchSite: "cross-site" }]) {
    assert.equal(authority.authorize({ ...request, ...change }).allowed, false);
  }
  const post = { ...request, pathname: "/auth/google/start", method: "POST" };
  assert.equal(authority.authorize(post).allowed, false);
  assert.equal(authority.authorize({ ...post, origin: "https://mentat.example", secFetchSite: "same-origin" }).allowed, true);
  assert.equal(authority.authorize({ ...request, pathname: "/auth/google/callback", secFetchSite: "cross-site" }).allowed, true);
  assert.equal(authority.authorize({ ...request, pathname: "/auth/google/callback", method: "HEAD" }).allowed, false);
});

test("only exact loopback supervisor health remains reachable without proxy headers", () => {
  const health = { host: "127.0.0.1:8888", pathname: "/api/gateway/health", method: "GET", origin: null, secFetchSite: null, forwardedHost: "127.0.0.1:8888", forwardedProto: "http", forwardedFor: "127.0.0.1", forwardedPort: "8888" };
  assert.equal(authority.authorize(health).allowed, true);
  assert.equal(authority.authorize({ ...health, pathname: "/api/tasks" }).allowed, false);
  assert.equal(authority.authorize({ ...health, host: "127.0.0.1:9999" }).allowed, false);
});

test("provider redirect chains may navigate documents but never bypass API metadata checks", () => {
  const navigation = { ...request, secFetchSite: "cross-site", secFetchMode: "navigate", secFetchDest: "document" };
  assert.equal(authority.authorize(navigation).allowed, true);
  assert.equal(authority.authorize({ ...navigation, pathname: "/sign-in" }).allowed, true);
  assert.equal(authority.authorize({ ...navigation, pathname: "/api/tasks" }).allowed, false);
  assert.equal(authority.authorize({ ...navigation, secFetchMode: "cors", secFetchDest: "empty" }).allowed, false);
});

test("duplicate cookies and unbound CSRF fail closed", () => {
  const cookie = "a".repeat(43), csrf = "b".repeat(43);
  assert.equal(ownerCookie(`${OWNER_COOKIE}=${cookie}; ${OWNER_COOKIE}=${cookie}`, OWNER_COOKIE), null);
  const headers = { cookie: `${OWNER_COOKIE}=${cookie}; ${OWNER_CSRF_COOKIE}=${csrf}` };
  assert.equal(sessionContext(new Request("https://mentat.example/api/tasks", { headers }), true), null);
  assert.deepEqual(sessionContext(new Request("https://mentat.example/api/tasks", { headers: { ...headers, "x-mentat-csrf": csrf } }), true), { cookie, csrf });
});
