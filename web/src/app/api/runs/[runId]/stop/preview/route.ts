import { BridgeRunStopError, fetchBridgeRunStopPreview } from "@/lib/bridge-run-stop";
import { hasExactEmptyJsonBody } from "@/lib/exact-json-body";
import { evaluateRequestBoundary, parseGatewayPort } from "@/lib/request-boundary";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const headers = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
function result(status: number, state: string) { return Response.json({ schema_version: 1, status: state }, { headers, status }); }
export async function POST(request: Request, context: { params: Promise<{ runId: string }> }) {
  const boundary = evaluateRequestBoundary({ expectedPort: parseGatewayPort(process.env.PORT), host: request.headers.get("host"), method: request.method, origin: request.headers.get("origin"), secFetchSite: request.headers.get("sec-fetch-site") });
  if (!boundary.allowed) return result(403, "error");
  if (!await hasExactEmptyJsonBody(request)) return result(400, "error");
  const { runId } = await context.params;
  try { return Response.json(await fetchBridgeRunStopPreview(runId), { headers }); }
  catch (error) { if (error instanceof BridgeRunStopError && error.code === "run_not_found") return result(404, "not_found"); if (error instanceof BridgeRunStopError && error.code === "action_conflict") return result(409, "conflict"); if (error instanceof BridgeRunStopError && error.code === "action_unsupported") return result(501, "unsupported"); if (error instanceof BridgeRunStopError && error.code === "bridge_unavailable") return result(503, "unavailable"); return result(502, "error"); }
}
