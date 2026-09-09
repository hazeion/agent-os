import { BridgeTasksError, fetchBridgeTasks, type PublicBridgeTasks } from "@/lib/bridge-tasks";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "@/lib/gateway-authority";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "@/lib/gateway-route-manifest";
import { withGatewayRoute } from "@/lib/gateway-request-context";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const headers = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };

function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}

const GET_RULE = route("GET", "/api/tasks");

function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}

export function createTasksGetHandler({
  fetchTasks = fetchBridgeTasks,
  gatewayPort = process.env.PORT,
}: Readonly<{
  fetchTasks?: () => Promise<PublicBridgeTasks>;
  gatewayPort?: string;
}> = {}) {
  return withGatewayRoute<boolean>(GET_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value: hasQuery }) => {
      if (hasQuery) return Response.json({ schema_version: 1, status: "error" }, { headers, status: 400 });
      try { return Response.json(await fetchTasks(), { headers }); }
      catch (error) {
        if (error instanceof BridgeTasksError && error.code === "bridge_unsupported") {
          return Response.json({ schema_version: 1, status: "unsupported" }, { headers, status: 501 });
        }
        if (error instanceof BridgeTasksError && error.code === "bridge_unavailable") {
          return Response.json({ schema_version: 1, status: "unavailable" }, { headers, status: 503 });
        }
        return Response.json({ schema_version: 1, status: "error" }, { headers, status: 502 });
      }
    },
    validator: { validate(request) { return Boolean(new URL(request.url).search); } },
  });
}

const get = createTasksGetHandler();

export async function GET(request: Request) {
  return get(request);
}
