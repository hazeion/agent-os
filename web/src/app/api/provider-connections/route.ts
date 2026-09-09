import {
  BridgeProviderConnectionsError,
  fetchBridgeProviderConnections,
  type PublicBridgeProviderConnections,
} from "@/lib/bridge-provider-connections";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "@/lib/gateway-authority";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "@/lib/gateway-route-manifest";
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

function fixedState(status: "error" | "unavailable" | "unsupported", code: number) {
  return Response.json(
    { schema_version: 1, status },
    { headers: HEADERS, status: code },
  );
}

function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}

const GET_RULE = route("GET", "/api/provider-connections");

function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}

export function createProviderConnectionsGetHandler({
  fetchConnections = fetchBridgeProviderConnections,
  gatewayPort = process.env.PORT,
}: Readonly<{
  fetchConnections?: () => Promise<PublicBridgeProviderConnections>;
  gatewayPort?: string;
}> = {}) {
  return withGatewayRoute<boolean>(GET_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value: hasQuery }) => {
      if (hasQuery) return fixedState("error", 400);
      try {
        return Response.json(await fetchConnections(), {
          headers: HEADERS,
          status: 200,
        });
      } catch (error) {
        if (
          error instanceof BridgeProviderConnectionsError
          && error.code === "bridge_unsupported"
        ) return fixedState("unsupported", 501);
        if (
          error instanceof BridgeProviderConnectionsError
          && error.code === "bridge_unavailable"
        ) return fixedState("unavailable", 503);
        return fixedState("error", 502);
      }
    },
    validator: { validate(request) { return Boolean(new URL(request.url).search); } },
  });
}

const get = createProviderConnectionsGetHandler();

export async function GET(request: Request) {
  return get(request);
}
