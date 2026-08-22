import { BridgeRunResponseError, confirmBridgeRunResponse, fetchBridgeRunResponseRequest } from "@/lib/bridge-run-response";
import { readRunResponseRouteBody } from "@/lib/exact-json-body";
import { evaluateRequestBoundary, parseGatewayPort } from "@/lib/request-boundary";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const headers = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function result(status: number, state: string) {
  return Response.json({ schema_version: 1, status: state }, { headers, status });
}

function errorResult(error: unknown) {
  if (error instanceof BridgeRunResponseError && error.code === "run_not_found") return result(404, "not_found");
  if (error instanceof BridgeRunResponseError && error.code === "action_conflict") return result(409, "conflict");
  if (error instanceof BridgeRunResponseError && error.code === "action_unsupported") return result(501, "unsupported");
  if (error instanceof BridgeRunResponseError && error.code === "bridge_unavailable") return result(503, "unavailable");
  if (error instanceof BridgeRunResponseError && error.code === "request_invalid") return result(400, "invalid");
  if (error instanceof BridgeRunResponseError && error.code === "action_partial") return result(502, "partial");
  return result(502, "error");
}

export async function POST(request: Request, context: { params: Promise<{ runId: string }> }) {
  const boundary = evaluateRequestBoundary({ expectedPort: parseGatewayPort(process.env.PORT), host: request.headers.get("host"), method: request.method, origin: request.headers.get("origin"), secFetchSite: request.headers.get("sec-fetch-site") });
  if (!boundary.allowed) return result(403, "error");
  const { runId } = await context.params;
  const body = await readRunResponseRouteBody(request);
  if (body === "request") {
    try { return Response.json(await fetchBridgeRunResponseRequest(runId), { headers }); }
    catch (error) { return errorResult(error); }
  }
  if (!body) return result(400, "error");
  try { return Response.json(await confirmBridgeRunResponse(runId, body.response, body.confirmationId), { headers, status: 202 }); }
  catch (error) { return errorResult(error); }
}
