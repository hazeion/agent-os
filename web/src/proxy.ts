import { type NextRequest, NextResponse } from "next/server";

import { PROCESS_GATEWAY_AUTHORITY } from "@/lib/gateway-authority";
import { sessionContext } from "@/lib/owner-cookies";
import { validateOwnerSession } from "@/lib/owner-bridge";

const FORBIDDEN_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Type": "text/plain; charset=utf-8",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function contentSecurityPolicy(nonce: string, login: boolean): string {
  return [
    "default-src 'self'",
    "base-uri 'none'",
    "connect-src 'self'",
    "font-src 'self'",
    login ? "form-action 'self' https://accounts.google.com" : "form-action 'self'",
    "frame-ancestors 'none'",
    "img-src 'self' data:",
    "object-src 'none'",
    `script-src 'self' 'nonce-${nonce}'`,
    "style-src 'self' 'unsafe-inline'",
  ].join("; ");
}

export async function proxy(request: NextRequest) {
  const decision = PROCESS_GATEWAY_AUTHORITY.authorize({
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    pathname: request.nextUrl.pathname,
    secFetchSite: request.headers.get("sec-fetch-site"),
    secFetchMode: request.headers.get("sec-fetch-mode"),
    secFetchDest: request.headers.get("sec-fetch-dest"),
    forwardedHost: request.headers.get("x-forwarded-host"),
    forwardedProto: request.headers.get("x-forwarded-proto"),
    forwardedFor: request.headers.get("x-forwarded-for"),
    forwardedPort: request.headers.get("x-forwarded-port"),
    forbiddenForwarding: ["forwarded", "x-real-ip"].some(name => request.headers.has(name)),
  });
  if (!decision.allowed) {
    return new NextResponse("Forbidden\n", {
      status: 403,
      headers: FORBIDDEN_HEADERS,
    });
  }
  if (PROCESS_GATEWAY_AUTHORITY.mode === "owner" && decision.route && ["owner_session", "owner_reauth"].includes(decision.route.exposure)) {
    const owner = sessionContext(request, decision.route.csrf === "session_bound");
    let authenticated = false;
    try { authenticated = Boolean(owner && await validateOwnerSession(owner)); }
    catch { return new NextResponse("Mentat could not verify sign-in. Please refresh shortly.\n", { status: 503, headers: FORBIDDEN_HEADERS }); }
    if (!authenticated) {
      if (request.method === "GET" && !request.nextUrl.pathname.startsWith("/api/")) {
        return NextResponse.redirect(new URL("/sign-in", PROCESS_GATEWAY_AUTHORITY.origin!), { status: 303, headers: FORBIDDEN_HEADERS });
      }
      return new NextResponse("Sign in required\n", { status: 401, headers: FORBIDDEN_HEADERS });
    }
  }
  const nonce = btoa(crypto.randomUUID());
  const login = request.nextUrl.pathname === "/sign-in" || request.nextUrl.pathname === "/auth/google/start";
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", contentSecurityPolicy(nonce, login));
  requestHeaders.set("x-nonce", nonce);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", contentSecurityPolicy(nonce, login));
  if (PROCESS_GATEWAY_AUTHORITY.mode === "owner") response.headers.set("Cache-Control", "private, no-store");
  if (request.nextUrl.pathname === "/sign-in") response.headers.set("Referrer-Policy", "same-origin");
  return response;
}

export const config = {
  matcher: ["/:path*"],
};
