import { BridgePlanningError, fetchBridgePlanningOverview } from "./bridge-planning.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";
import type { PublicPlanningOverview } from "./public-planning.ts";

export const PLANNING_HEADERS = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
export function planningFixed(status: string, code: number) { return Response.json({ schema_version: 1, status }, { headers: PLANNING_HEADERS, status: code }); }
export function planningFailure(error: unknown) {
  if (!(error instanceof BridgePlanningError)) return planningFixed("error", 502);
  const mapped: Record<string, [string, number]> = { bridge_unavailable: ["unavailable", 503], bridge_unsupported: ["unsupported", 501], planning_request_invalid: ["invalid", 400], planning_not_found: ["not_found", 404], planning_conflict: ["conflict", 409], planning_active_run: ["active_run", 409], planning_queue_active: ["queue_active", 409] };
  const result = mapped[error.code]; return result ? planningFixed(result[0], result[1]) : planningFixed("error", 502);
}
export function planningRequestAllowed(request: Request, gatewayPort: string | undefined) {
  return evaluateRequestBoundary({ expectedPort: parseGatewayPort(gatewayPort), host: request.headers.get("host"), method: request.method, origin: request.headers.get("origin"), secFetchSite: request.headers.get("sec-fetch-site") }).allowed;
}

export function createPlanningOverviewHandler({ fetchOverview = fetchBridgePlanningOverview, gatewayPort = process.env.PORT }: Readonly<{ fetchOverview?: () => Promise<PublicPlanningOverview>; gatewayPort?: string }> = {}) {
  return async function getPlanningOverview(request: Request) {
    if (!planningRequestAllowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: PLANNING_HEADERS, status: 403 });
    if (new URL(request.url).search) return planningFixed("invalid", 400);
    try { return Response.json(await fetchOverview(), { headers: PLANNING_HEADERS }); } catch (error) { return planningFailure(error); }
  };
}
