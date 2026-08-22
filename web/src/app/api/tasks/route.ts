import { BridgeTasksError, fetchBridgeTasks } from "@/lib/bridge-tasks";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const headers = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
export async function GET() {
  try { return Response.json(await fetchBridgeTasks(), { headers }); }
  catch (error) {
    if (error instanceof BridgeTasksError && error.code === "bridge_unsupported") {
      return Response.json({ schema_version: 1, status: "unsupported" }, { headers, status: 501 });
    }
    if (error instanceof BridgeTasksError && error.code === "bridge_unavailable") {
      return Response.json({ schema_version: 1, status: "unavailable" }, { headers, status: 503 });
    }
    return Response.json({ schema_version: 1, status: "error" }, { headers, status: 502 });
  }
}
