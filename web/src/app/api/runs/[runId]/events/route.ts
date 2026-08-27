import { lastEventCursor, refreshAndFetchBridgeRunEvents, validRunId } from "@/lib/bridge-run-events";
import { evaluateRequestBoundary, parseGatewayPort } from "@/lib/request-boundary";
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

export async function GET(request: Request, context: { params: Promise<{ runId: string }> }) {
  const boundary = evaluateRequestBoundary({
    expectedPort: parseGatewayPort(process.env.PORT),
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
  });
  if (!boundary.allowed) return new Response("Forbidden\n", { headers: errorHeaders, status: 403 });
  const { runId } = await context.params;
  const lastEventId = request.headers.get("last-event-id");
  const after = lastEventCursor(lastEventId);
  if (!validRunId(runId) || after === null || new URL(request.url).search) {
    return Response.json({ schema_version: 1, status: "error" }, { headers: errorHeaders, status: 400 });
  }
  return new Response(createRunTimelineStream({ runId, after, read: refreshAndFetchBridgeRunEvents, signal: request.signal }), { headers: streamHeaders });
}
