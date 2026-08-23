import {
  BridgeProviderConnectionsError,
  fetchBridgeProviderConnections,
} from "@/lib/bridge-provider-connections";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixedState(status: "error" | "unavailable" | "unsupported", code: number) {
  return Response.json(
    { schema_version: 1, status },
    { headers: HEADERS, status: code },
  );
}

export async function GET() {
  try {
    return Response.json(await fetchBridgeProviderConnections(), {
      headers: HEADERS,
      status: 200,
    });
  } catch (error) {
    if (
      error instanceof BridgeProviderConnectionsError
      && error.code === "bridge_unsupported"
    ) return fixedState("unsupported", 501);
    if (
      error instanceof BridgeProviderConnectionsError
      && error.code === "bridge_unavailable"
    ) return fixedState("unavailable", 503);
    return fixedState("error", 502);
  }
}
