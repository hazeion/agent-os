import {
  BridgeConversationsError,
  fetchBridgeActivity,
} from "@/lib/bridge-conversations";
import { evaluateRequestBoundary, parseGatewayPort } from "@/lib/request-boundary";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixed(status: "error" | "unavailable" | "unsupported", code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

export async function GET(request: Request) {
  const decision = evaluateRequestBoundary({
    expectedPort: parseGatewayPort(process.env.PORT),
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
  });
  if (!decision.allowed) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
  if (new URL(request.url).search) return fixed("error", 400);
  try {
    return Response.json(await fetchBridgeActivity(), { headers: HEADERS });
  } catch (error) {
    if (error instanceof BridgeConversationsError && error.code === "bridge_unsupported") return fixed("unsupported", 501);
    if (error instanceof BridgeConversationsError && error.code === "bridge_unavailable") return fixed("unavailable", 503);
    return fixed("error", 502);
  }
}
