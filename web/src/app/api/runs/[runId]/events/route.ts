import { lastEventCursor, refreshAndFetchBridgeRunEvents, validRunId } from "@/lib/bridge-run-events";
import { GATEWAY_ROUTE_MANIFEST } from "@/lib/gateway-route-manifest";
import { withGatewayRoute } from "@/lib/gateway-request-context";
import { createRunTimelineStream } from "@/lib/run-timeline-stream";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const streamHeaders = {
  "Cache-Control": "private, no-store, no-transform",
  Connection: "keep-alive",
  "Content-Type": "text/event-stream; charset=utf-8",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Accel-Buffering": "no",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};
const errorHeaders = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };

const GET_RULE = GATEWAY_ROUTE_MANIFEST.find((rule) => rule.method === "GET" && rule.path === "/api/runs/[runId]/events");
if (!GET_RULE) throw new Error("missing gateway manifest rule for GET /api/runs/[runId]/events");

type RouteContext = { params: Promise<{ runId: string }> };
type TimelineInput = { after: number; runId: string; signal: AbortSignal } | null;

const get = withGatewayRoute<TimelineInput, RouteContext>(GET_RULE, {
  handler: ({ value }) => {
    if (!value) return Response.json({ schema_version: 1, status: "error" }, { headers: errorHeaders, status: 400 });
    return new Response(createRunTimelineStream({ runId: value.runId, after: value.after, read: refreshAndFetchBridgeRunEvents, signal: value.signal }), { headers: streamHeaders });
  },
  validator: {
    async validate(request, _approved, context) {
      const { runId } = await context.params;
      const after = lastEventCursor(request.headers.get("last-event-id"));
      if (!validRunId(runId) || after === null || new URL(request.url).search) return null;
      return { after, runId, signal: request.signal };
    },
  },
});

export async function GET(request: Request, context: RouteContext) { return get(request, context); }
