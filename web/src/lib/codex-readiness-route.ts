import {
  BridgeConversationsError,
  fetchBridgeCodexReadiness,
  type PublicCodexReadiness,
} from "./bridge-conversations.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixed(status: "error" | "unavailable", code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

export function createCodexReadinessGetHandler({
  fetchReadiness = fetchBridgeCodexReadiness,
  gatewayPort = process.env.PORT,
}: Readonly<{
  fetchReadiness?: () => Promise<PublicCodexReadiness>;
  gatewayPort?: string;
}> = {}) {
  return async function getCodexReadiness(request: Request) {
    const decision = evaluateRequestBoundary({
      expectedPort: parseGatewayPort(gatewayPort),
      host: request.headers.get("host"),
      method: request.method,
      origin: request.headers.get("origin"),
      secFetchSite: request.headers.get("sec-fetch-site"),
    });
    if (!decision.allowed) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
    if (new URL(request.url).search) return fixed("error", 400);
    try {
      return Response.json(await fetchReadiness(), { headers: HEADERS });
    } catch (error) {
      if (error instanceof BridgeConversationsError && error.code === "bridge_unavailable") {
        return fixed("unavailable", 503);
      }
      return fixed("error", 502);
    }
  };
}
