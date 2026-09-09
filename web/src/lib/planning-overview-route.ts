import { BridgePlanningError, fetchBridgePlanningOverview } from "./bridge-planning.ts";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "./gateway-route-manifest.ts";
import { withGatewayRoute, type GatewayRouteHandler, type GatewayRouteValidator } from "./gateway-request-context.ts";
import type { PublicPlanningOverview } from "./public-planning.ts";

export const PLANNING_HEADERS = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
export function planningFixed(status: string, code: number) { return Response.json({ schema_version: 1, status }, { headers: PLANNING_HEADERS, status: code }); }
export function planningFailure(error: unknown) {
  if (!(error instanceof BridgePlanningError)) return planningFixed("error", 502);
  const mapped: Record<string, [string, number]> = { bridge_unavailable: ["unavailable", 503], bridge_unsupported: ["unsupported", 501], planning_request_invalid: ["invalid", 400], planning_not_found: ["not_found", 404], planning_conflict: ["conflict", 409], planning_active_run: ["active_run", 409], planning_queue_active: ["queue_active", 409] };
  const result = mapped[error.code]; return result ? planningFixed(result[0], result[1]) : planningFixed("error", 502);
}
export function planningGatewayRule(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}
const GET_RULE = planningGatewayRule("GET", "/api/agent-console/planning-overview");
export function planningGatewayAuthority(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}

/** Planning adapters share the fixed manifest lookup and process authority, never a permissive local check. */
export function withPlanningGatewayRoute<Value, RouteContext = void>(
  method: GatewayRouteRule["method"],
  path: GatewayRouteRule["path"],
  gatewayPort: string | undefined,
  options: Readonly<{ handler: GatewayRouteHandler<Value>; validator: GatewayRouteValidator<Value, RouteContext> }>,
) {
  return withGatewayRoute<Value, RouteContext>(planningGatewayRule(method, path), {
    authority: planningGatewayAuthority(gatewayPort),
    ...options,
  });
}

export function createPlanningOverviewHandler({ fetchOverview = fetchBridgePlanningOverview, gatewayPort = process.env.PORT }: Readonly<{ fetchOverview?: () => Promise<PublicPlanningOverview>; gatewayPort?: string }> = {}) {
  return withGatewayRoute<boolean>(GET_RULE, {
    authority: planningGatewayAuthority(gatewayPort),
    handler: async ({ value: hasQuery }) => {
      if (hasQuery) return planningFixed("invalid", 400);
      try { return Response.json(await fetchOverview(), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
    },
    validator: { validate(request) { return Boolean(new URL(request.url).search); } },
  });
}
