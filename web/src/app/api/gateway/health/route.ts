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

const GET_RULE = route("GET", "/api/gateway/health");

function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}

/** A fixed readiness check for the public Node gateway only. */
export function createGatewayHealthGetHandler({ gatewayPort = process.env.PORT }: Readonly<{ gatewayPort?: string }> = {}) {
  return withGatewayRoute<boolean>(GET_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value: hasQuery }) => hasQuery
      ? Response.json({ schema_version: 1, status: "error" }, { headers: RESPONSE_HEADERS, status: 400 })
      : Response.json({ gateway: "mentat-node-gateway", status: "ready" }, { headers: RESPONSE_HEADERS, status: 200 }),
    validator: { validate(request) { return Boolean(new URL(request.url).search); } },
  });
}

const get = createGatewayHealthGetHandler();

export async function GET(request: Request) {
  return get(request);
}
