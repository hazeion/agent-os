import {
  BridgeConversationsError,
  fetchBridgeConversation,
} from "@/lib/bridge-conversations";
import { evaluateRequestBoundary, parseGatewayPort } from "@/lib/request-boundary";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixed(status: "error" | "not_found" | "unavailable" | "unsupported", code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

export async function GET(request: Request, context: { params: Promise<{ conversationId: string }> }) {
  const decision = evaluateRequestBoundary({
    expectedPort: parseGatewayPort(process.env.PORT),
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
  });
  if (!decision.allowed) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
  const { conversationId } = await context.params;
  const entries = [...new URL(request.url).searchParams.entries()];
  if (entries.length > 1 || entries.length === 1 && (entries[0][0] !== "before" || !/^[1-9][0-9]{0,9}$/u.test(entries[0][1]))) return fixed("error", 400);
  const before = entries[0]?.[1] ?? null;
  try {
    return Response.json(await fetchBridgeConversation(conversationId, before), { headers: HEADERS });
  } catch (error) {
    if (error instanceof BridgeConversationsError && error.code === "conversation_id_invalid") return fixed("error", 400);
    if (error instanceof BridgeConversationsError && error.code === "conversation_not_found") return fixed("not_found", 404);
    if (error instanceof BridgeConversationsError && error.code === "bridge_unsupported") return fixed("unsupported", 501);
    if (error instanceof BridgeConversationsError && error.code === "bridge_unavailable") return fixed("unavailable", 503);
    return fixed("error", 502);
  }
}
