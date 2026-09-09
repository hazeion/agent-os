import { BridgeRunStopError, confirmBridgeRunStop } from "@/lib/bridge-run-stop";
import { readConfirmationId } from "@/lib/exact-json-body";
import { GATEWAY_ROUTE_MANIFEST } from "@/lib/gateway-route-manifest";
import { withGatewayRoute } from "@/lib/gateway-request-context";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const headers = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
function result(status: number, state: string) { return Response.json({ schema_version: 1, status: state }, { headers, status }); }
const POST_RULE = GATEWAY_ROUTE_MANIFEST.find((rule) => rule.method === "POST" && rule.path === "/api/runs/[runId]/stop");
if (!POST_RULE) throw new Error("missing gateway manifest rule for POST /api/runs/[runId]/stop");

type RouteContext = { params: Promise<{ runId: string }> };
type StopInput = { confirmationId: string; runId: string } | null;

const post = withGatewayRoute<StopInput, RouteContext>(POST_RULE, {
  handler: async ({ value }) => {
    if (!value) return result(400, "error");
    try { return Response.json(await confirmBridgeRunStop(value.runId, value.confirmationId), { headers, status: 202 }); }
    catch (error) { if (error instanceof BridgeRunStopError && error.code === "run_not_found") return result(404, "not_found"); if (error instanceof BridgeRunStopError && error.code === "action_conflict") return result(409, "conflict"); if (error instanceof BridgeRunStopError && error.code === "action_unsupported") return result(501, "unsupported"); if (error instanceof BridgeRunStopError && error.code === "bridge_unavailable") return result(503, "unavailable"); return result(502, "error"); }
  },
  validator: {
    async validate(request, _approved, context) {
      const confirmationId = await readConfirmationId(request);
      if (!confirmationId) return null;
      const { runId } = await context.params;
      return { confirmationId, runId };
    },
  },
});

export async function POST(request: Request, context: RouteContext) { return post(request, context); }
