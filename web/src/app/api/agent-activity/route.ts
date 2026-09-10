import {
  BridgeConversationsError,
  fetchBridgeActivity,
} from "@/lib/bridge-conversations";
import { GATEWAY_ROUTE_MANIFEST } from "@/lib/gateway-route-manifest";
import { withGatewayRoute } from "@/lib/gateway-request-context";

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

const GET_RULE = GATEWAY_ROUTE_MANIFEST.find((rule) => rule.method === "GET" && rule.path === "/api/agent-activity");
if (!GET_RULE) throw new Error("missing gateway manifest rule for GET /api/agent-activity");

const get = withGatewayRoute(GET_RULE, {
  handler: async ({ value: hasQuery }) => {
    if (hasQuery) return fixed("error", 400);
    try {
      return Response.json(await fetchBridgeActivity(), { headers: HEADERS });
    } catch (error) {
      if (error instanceof BridgeConversationsError && error.code === "bridge_unsupported") return fixed("unsupported", 501);
      if (error instanceof BridgeConversationsError && error.code === "bridge_unavailable") return fixed("unavailable", 503);
      return fixed("error", 502);
    }
  },
  validator: {
    validate(request) {
      return Boolean(new URL(request.url).search);
    },
  },
});

export async function GET(request: Request) {
  return get(request);
}
