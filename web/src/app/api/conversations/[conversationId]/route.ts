import {
  BridgeConversationsError,
  fetchBridgeConversation,
} from "@/lib/bridge-conversations";
import { GATEWAY_ROUTE_MANIFEST } from "@/lib/gateway-route-manifest";
import { withGatewayRoute } from "@/lib/gateway-request-context";

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

const GET_RULE = GATEWAY_ROUTE_MANIFEST.find((rule) => rule.method === "GET" && rule.path === "/api/conversations/[conversationId]");
if (!GET_RULE) throw new Error("missing gateway manifest rule for GET /api/conversations/[conversationId]");

type RouteContext = { params: Promise<{ conversationId: string }> };
type ConversationInput = { before: string | null; conversationId: string } | null;

const get = withGatewayRoute<ConversationInput, RouteContext>(GET_RULE, {
  handler: async ({ value }) => {
    if (!value) return fixed("error", 400);
    try {
      return Response.json(await fetchBridgeConversation(value.conversationId, value.before), { headers: HEADERS });
    } catch (error) {
      if (error instanceof BridgeConversationsError && error.code === "conversation_id_invalid") return fixed("error", 400);
      if (error instanceof BridgeConversationsError && error.code === "conversation_not_found") return fixed("not_found", 404);
      if (error instanceof BridgeConversationsError && error.code === "bridge_unsupported") return fixed("unsupported", 501);
      if (error instanceof BridgeConversationsError && error.code === "bridge_unavailable") return fixed("unavailable", 503);
      return fixed("error", 502);
    }
  },
  validator: {
    async validate(request, _approved, context) {
      const entries = [...new URL(request.url).searchParams.entries()];
      if (entries.length > 1 || entries.length === 1 && (entries[0]?.[0] !== "before" || !/^[1-9][0-9]{0,9}$/u.test(entries[0]?.[1] ?? ""))) return null;
      const { conversationId } = await context.params;
      return { before: entries[0]?.[1] ?? null, conversationId };
    },
  },
});

export async function GET(request: Request, context: RouteContext) { return get(request, context); }
