import { BridgeHealthError, fetchBridgeHealth } from "@/lib/bridge-health";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const RESPONSE_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

export async function GET() {
  try {
    return Response.json({ gateway: "mentat-node-gateway", ...await fetchBridgeHealth() }, {
      headers: RESPONSE_HEADERS,
      status: 200,
    });
  } catch (error) {
    return Response.json(
      {
        error: error instanceof BridgeHealthError ? error.code : "bridge_unavailable",
        gateway: "mentat-node-gateway",
        runtime: "python",
        schema_version: 1,
        service: "mentat-local-bridge",
        status: "unavailable",
      },
      { headers: RESPONSE_HEADERS, status: 503 },
    );
  }
}
