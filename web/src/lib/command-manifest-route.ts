import {
  BridgeCommandManifestError,
  fetchBridgeCommandManifest,
} from "./bridge-command-manifest.ts";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "./gateway-route-manifest.ts";
import { withGatewayRoute } from "./gateway-request-context.ts";
import type { PublicCommandManifest } from "./public-command-manifest.ts";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixed(status: string, code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}
const GET_RULE = route("GET", "/api/agent-console/commands");
function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}

export function createCommandManifestHandler({
  fetchManifest = fetchBridgeCommandManifest,
  gatewayPort = process.env.PORT,
}: Readonly<{
  fetchManifest?: () => Promise<PublicCommandManifest>;
  gatewayPort?: string;
}> = {}) {
  return withGatewayRoute<boolean>(GET_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value: hasQuery }) => {
      if (hasQuery) return fixed("invalid", 400);
      try {
        return Response.json(await fetchManifest(), { headers: HEADERS });
      } catch (error) {
        if (error instanceof BridgeCommandManifestError && error.code === "bridge_unavailable") {
          return fixed("unavailable", 503);
        }
        return fixed("error", 502);
      }
    },
    validator: { validate(request) { return Boolean(new URL(request.url).search); } },
  });
}
