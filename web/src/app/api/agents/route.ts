import { BridgeAgentsError, fetchBridgeAgents, type PublicBridgeAgents } from "@/lib/bridge-agents";
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

function fixedState(status: "error" | "unavailable" | "unsupported", responseStatus: number) {
  return Response.json(
    { schema_version: 1, status },
    { headers: RESPONSE_HEADERS, status: responseStatus },
  );
}

function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}

const GET_RULE = route("GET", "/api/agents");

function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}

export function createAgentsGetHandler({
  fetchAgents = fetchBridgeAgents,
  gatewayPort = process.env.PORT,
}: Readonly<{
  fetchAgents?: () => Promise<PublicBridgeAgents>;
  gatewayPort?: string;
}> = {}) {
  return withGatewayRoute<boolean>(GET_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value: hasQuery }) => {
      if (hasQuery) return fixedState("error", 400);
      try {
        return Response.json(await fetchAgents(), {
          headers: RESPONSE_HEADERS,
          status: 200,
        });
      } catch (error) {
        if (error instanceof BridgeAgentsError && error.code === "bridge_unsupported") {
          return fixedState("unsupported", 501);
        }
        if (error instanceof BridgeAgentsError && error.code === "bridge_unavailable") {
          return fixedState("unavailable", 503);
        }
        return fixedState("error", 502);
      }
    },
    validator: { validate(request) { return Boolean(new URL(request.url).search); } },
  });
}

const get = createAgentsGetHandler();

export async function GET(request: Request) {
  return get(request);
}
