import { type NextRequest, NextResponse } from "next/server";

import { evaluateRequestBoundary, parseGatewayPort } from "@/lib/request-boundary";

const FORBIDDEN_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Type": "text/plain; charset=utf-8",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function contentSecurityPolicy(nonce: string): string {
  return [
    "default-src 'self'",
    "base-uri 'none'",
    "connect-src 'self'",
    "font-src 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "img-src 'self' data:",
    "object-src 'none'",
    `script-src 'self' 'nonce-${nonce}'`,
    "style-src 'self' 'unsafe-inline'",
  ].join("; ");
}

export function proxy(request: NextRequest) {
  const decision = evaluateRequestBoundary({
    expectedPort: parseGatewayPort(process.env.PORT),
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
  });
  if (!decision.allowed) {
    return new NextResponse("Forbidden\n", {
      status: 403,
      headers: FORBIDDEN_HEADERS,
    });
  }
  const nonce = btoa(crypto.randomUUID());
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", contentSecurityPolicy(nonce));
  requestHeaders.set("x-nonce", nonce);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", contentSecurityPolicy(nonce));
  return response;
}

export const config = {
  matcher: ["/:path*"],
};
