import { BridgeHealthError, fetchBridgeHealth, type PublicBridgeHealth } from "@/lib/bridge-health";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "@/lib/gateway-authority";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "@/lib/gateway-route-manifest";
import { withGatewayRoute } from "@/lib/gateway-request-context";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const RESPONSE_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}

const GET_RULE = route("GET", "/api/bridge/health");

function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}

export function createBridgeHealthGetHandler({
  fetchHealth = fetchBridgeHealth,
  gatewayPort = process.env.PORT,
}: Readonly<{
  fetchHealth?: () => Promise<PublicBridgeHealth>;
  gatewayPort?: string;
}> = {}) {
  return withGatewayRoute<boolean>(GET_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value: hasQuery }) => {
      if (hasQuery) {
        return Response.json({ schema_version: 1, status: "error" }, { headers: RESPONSE_HEADERS, status: 400 });
      }
      try {
        return Response.json({ gateway: "mentat-node-gateway", ...await fetchHealth() }, {
          headers: RESPONSE_HEADERS,
          status: 200,
        });
      } catch (error) {
        return Response.json(
          {
            error: error instanceof BridgeHealthError ? error.code : "bridge_unavailable",
            gateway: "mentat-node-gateway",
            runtime: "python",
            schema_version: 1,
            service: "mentat-local-bridge",
            status: "unavailable",
          },
          { headers: RESPONSE_HEADERS, status: 503 },
        );
      }
    },
    validator: { validate(request) { return Boolean(new URL(request.url).search); } },
  });
}

const get = createBridgeHealthGetHandler();

export async function GET(request: Request) {
  return get(request);
}
