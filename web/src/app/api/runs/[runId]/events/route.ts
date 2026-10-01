import { lastEventCursor, refreshAndFetchBridgeRunEvents, validRunId } from "@/lib/bridge-run-events";
import { GATEWAY_ROUTE_MANIFEST } from "@/lib/gateway-route-manifest";
import { withGatewayRoute } from "@/lib/gateway-request-context";
import { createRunTimelineStream } from "@/lib/run-timeline-stream";
import { currentOwnerContext, runWithOwnerContext } from "@/lib/owner-request-context";
import { OwnerBridgeError, ownerCapability } from "@/lib/owner-bridge";

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
  handler: async ({ value }) => {
    if (!value) return Response.json({ schema_version: 1, status: "error" }, { headers: errorHeaders, status: 400 });
    const owner = currentOwnerContext();
    if (owner) {
      try {
        const reserved = await ownerCapability("sse-reserve", { cookie: owner.cookie });
        if (Object.keys(reserved).sort().join() !== "lease,ok" || typeof reserved.lease !== "string" || !/^[A-Za-z0-9_-]{32}$/u.test(reserved.lease)) throw new Error();
        const lease = reserved.lease;
        const authorize = async () => { try { const checked = await ownerCapability("sse-check", { cookie: owner.cookie, lease }); return Object.keys(checked).join() === "ok"; } catch (error) { if (error instanceof OwnerBridgeError && error.kind === "unauthenticated") return false; throw error; } };
        const read = (runId: string, after: number) => runWithOwnerContext({ ...owner, lease }, () => refreshAndFetchBridgeRunEvents(runId, after));
        const release = async () => { await ownerCapability("sse-release", { cookie: owner.cookie, lease }); };
        return new Response(createRunTimelineStream({ runId: value.runId, after: value.after, read, signal: value.signal, authorize, release }), { headers: streamHeaders });
      } catch (error) { return Response.json({ status: "unavailable" }, { status: error instanceof OwnerBridgeError && error.kind === "unauthenticated" ? 401 : 503, headers: errorHeaders }); }
    }
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
