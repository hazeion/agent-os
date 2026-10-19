import { NextResponse } from "next/server.js";
import { PROCESS_GATEWAY_AUTHORITY } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST } from "./gateway-route-manifest.ts";
import { withGatewayRoute } from "./gateway-request-context.ts";
import { OwnerBridgeError, ownerCapability } from "./owner-bridge.ts";
import { currentOwnerContext } from "./owner-request-context.ts";
import { LOGIN_COOKIE, OWNER_COOKIE, OWNER_CSRF_COOKIE, ownerCookie } from "./owner-cookies.ts";

const safeHeaders = { "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer" };
async function smallBody(request: Request): Promise<string | null> {
  const declared = request.headers.get("content-length");
  if (declared && (!/^[0-9]{1,3}$/u.test(declared) || Number(declared) > 128)) { void request.body?.cancel(); return null; }
  if (!request.body) return "";
  const reader = request.body.getReader();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const read = async () => {
      const chunks: Uint8Array[] = []; let size = 0;
      while (true) { const item = await reader.read(); if (item.done) break; size += item.value.length; if (size > 128) throw new Error(); chunks.push(item.value); }
      const raw = new Uint8Array(size); let offset = 0;
      for (const chunk of chunks) { raw.set(chunk, offset); offset += chunk.length; }
      return new TextDecoder("utf-8", { fatal: true }).decode(raw);
    };
    return await Promise.race([read(), new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(new Error()), 5000); })]);
  } catch { void reader.cancel().catch(() => {}); return null; }
  finally { clearTimeout(timer); reader.releaseLock(); }
}
function rule(method: string, path: string) {
  const value = GATEWAY_ROUTE_MANIFEST.find(item => item.method === method && item.path === path);
  if (!value) throw new Error("Missing owner route");
  return value;
}
function redirect(path: string) {
  return NextResponse.redirect(new URL(path, PROCESS_GATEWAY_AUTHORITY.origin!), { status: 303, headers: safeHeaders });
}
function clearLogin(response: NextResponse) {
  response.cookies.set(LOGIN_COOKIE, "", { secure: true, httpOnly: true, sameSite: "lax", path: "/", maxAge: 0 });
  return response;
}
function clearSession(response: NextResponse) {
  for (const name of [OWNER_COOKIE, OWNER_CSRF_COOKIE]) response.cookies.set(name, "", { secure: true, httpOnly: name === OWNER_COOKIE, sameSite: "lax", path: "/", maxAge: 0 });
  return response;
}

export const startGoogleLogin = withGatewayRoute(rule("POST", "/auth/google/start"), {
  validator: { async validate(request) { return !new URL(request.url).search && await smallBody(request) === ""; } },
  handler: async ({ value }) => {
    if (PROCESS_GATEWAY_AUTHORITY.mode !== "owner") return new Response(null, { status: 404 });
    if (!value) return redirect("/sign-in?status=failed");
    try {
      const result = await ownerCapability("login-start", {});
      if (Object.keys(result).sort().join() !== "authorization_url,browser_binding,ok" || typeof result.authorization_url !== "string" || result.authorization_url.length > 4096 || typeof result.browser_binding !== "string" || !/^[A-Za-z0-9_-]{43}$/u.test(result.browser_binding)) throw new Error();
      const target = new URL(result.authorization_url);
      if (target.origin !== "https://accounts.google.com" || target.pathname !== "/o/oauth2/v2/auth") throw new Error();
      const response = NextResponse.redirect(target, { status: 303, headers: safeHeaders });
      response.cookies.set(LOGIN_COOKIE, result.browser_binding, { secure: true, httpOnly: true, sameSite: "lax", path: "/", maxAge: 300 });
      return response;
    } catch { return redirect("/sign-in?status=unavailable"); }
  },
});

export const completeGoogleLogin = withGatewayRoute(rule("GET", "/auth/google/callback"), {
  validator: { validate(request) {
    if (request.method !== "GET") return null;
    const query = new URL(request.url).searchParams;
    if ([...query].some(([key, value]) => !["state", "code", "scope", "authuser", "prompt", "error", "error_description", "error_uri"].includes(key) || query.getAll(key).length !== 1 || value.length > 4096)) return null;
    const state = query.get("state"), code = query.get("code"), binding = ownerCookie(request.headers.get("cookie"), LOGIN_COOKIE);
    if (query.get("error") === "access_denied" && state && /^[A-Za-z0-9_-]{43}$/u.test(state) && binding) return { cancelled: true as const, state, browser_binding: binding };
    return state && /^[A-Za-z0-9_-]{43}$/u.test(state) && code && !query.has("error") && binding ? { cancelled: false as const, state, code, browser_binding: binding } : null;
  } },
  handler: async ({ value }) => {
    if (PROCESS_GATEWAY_AUTHORITY.mode !== "owner") return new Response(null, { status: 404 });
    if (value?.cancelled) {
      try { await ownerCapability("login-cancel", { state: value.state, browser_binding: value.browser_binding }); }
      catch { return clearLogin(redirect("/sign-in?status=failed")); }
      return clearLogin(redirect("/sign-in?status=cancelled"));
    }
    if (!value) return clearLogin(redirect("/sign-in?status=failed"));
    try {
      const result = await ownerCapability("login-callback", { state: value.state, code: value.code, browser_binding: value.browser_binding });
      if (Object.keys(result).sort().join() !== "cookie,csrf,ok" || typeof result.cookie !== "string" || typeof result.csrf !== "string" || !/^[A-Za-z0-9_-]{43}$/u.test(result.cookie) || !/^[A-Za-z0-9_-]{43}$/u.test(result.csrf)) throw new Error();
      const response = clearLogin(redirect("/"));
      response.cookies.set(OWNER_COOKIE, result.cookie, { secure: true, httpOnly: true, sameSite: "lax", path: "/", maxAge: 86400 });
      response.cookies.set(OWNER_CSRF_COOKIE, result.csrf, { secure: true, httpOnly: false, sameSite: "strict", path: "/", maxAge: 86400 });
      return response;
    } catch (error) { return clearLogin(redirect(`/sign-in?status=${error instanceof OwnerBridgeError ? error.reason : "failed"}`)); }
  },
});

export const readOwnerSession = withGatewayRoute(rule("GET", "/api/auth/session"), {
  validator: { validate(request) { return !new URL(request.url).search; } },
  handler: async ({ value }) => {
    if (!value) return NextResponse.json({ status: "invalid" }, { status: 400, headers: safeHeaders });
    if (PROCESS_GATEWAY_AUTHORITY.mode === "local") return NextResponse.json({ schema_version: 1, mode: "local" }, { headers: safeHeaders });
    try {
      const result = await ownerCapability("session", { cookie: currentOwnerContext()!.cookie });
      if (Object.keys(result).sort().join() !== "absolute_expires_at,ok" || typeof result.absolute_expires_at !== "number" || !Number.isFinite(result.absolute_expires_at)) throw new Error();
      return NextResponse.json({ schema_version: 1, mode: "owner", absolute_expires_at: result.absolute_expires_at }, { headers: safeHeaders });
    } catch { return NextResponse.json({ status: "unauthenticated" }, { status: 401, headers: safeHeaders }); }
  },
});

export function signOutOwner(all: boolean) {
  return withGatewayRoute(rule("POST", all ? "/api/auth/sign-out-all" : "/api/auth/sign-out"), {
    validator: { async validate(request) { return !new URL(request.url).search && await smallBody(request) === "{}"; } },
    handler: async ({ value }) => {
      if (!value || PROCESS_GATEWAY_AUTHORITY.mode !== "owner") return NextResponse.json({ status: "invalid" }, { status: 400, headers: safeHeaders });
      try {
        const owner = currentOwnerContext()!;
        await ownerCapability(all ? "sign-out-all" : "sign-out", { cookie: owner.cookie, csrf: owner.csrf });
        return clearSession(NextResponse.json({ status: "signed_out" }, { headers: safeHeaders }));
      } catch { return NextResponse.json({ status: "unavailable" }, { status: 409, headers: safeHeaders }); }
    },
  });
}
