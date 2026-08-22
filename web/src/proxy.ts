import { type NextRequest, NextResponse } from "next/server";

import { evaluateRequestBoundary, parseGatewayPort } from "@/lib/request-boundary";

const FORBIDDEN_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Type": "text/plain; charset=utf-8",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

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
  return NextResponse.next();
}

export const config = {
  matcher: ["/:path*"],
};
