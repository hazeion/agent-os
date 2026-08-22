import { BridgeAgentsError, fetchBridgeAgents } from "@/lib/bridge-agents";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const RESPONSE_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixedState(status: "error" | "unavailable" | "unsupported", responseStatus: number) {
  return Response.json(
    { schema_version: 1, status },
    { headers: RESPONSE_HEADERS, status: responseStatus },
  );
}

export async function GET() {
  try {
    return Response.json(await fetchBridgeAgents(), {
      headers: RESPONSE_HEADERS,
      status: 200,
    });
  } catch (error) {
    if (error instanceof BridgeAgentsError && error.code === "bridge_unsupported") {
      return fixedState("unsupported", 501);
    }
    if (error instanceof BridgeAgentsError && error.code === "bridge_unavailable") {
      return fixedState("unavailable", 503);
    }
    return fixedState("error", 502);
  }
}
