import {
  BridgeConversationsError,
  createBridgeConversation,
  fetchBridgeConversations,
} from "@/lib/bridge-conversations";
import { readConversationCreateBody } from "@/lib/exact-json-body";
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

function state(status: "error" | "not_found" | "unavailable" | "unsupported", code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

function errorResponse(error: unknown) {
  if (error instanceof BridgeConversationsError && error.code === "bridge_unsupported") return state("unsupported", 501);
  if (error instanceof BridgeConversationsError && error.code === "bridge_unavailable") return state("unavailable", 503);
  return state("error", 502);
}

const GET_RULE = GATEWAY_ROUTE_MANIFEST.find((rule) => rule.method === "GET" && rule.path === "/api/conversations");
const POST_RULE = GATEWAY_ROUTE_MANIFEST.find((rule) => rule.method === "POST" && rule.path === "/api/conversations");
if (!GET_RULE || !POST_RULE) throw new Error("missing gateway manifest rule for /api/conversations");

const get = withGatewayRoute<string | null | undefined>(GET_RULE, {
  handler: async ({ value: cursor }) => {
    if (cursor === undefined) return state("error", 400);
    try {
      return Response.json(await fetchBridgeConversations(undefined, undefined, cursor), { headers: HEADERS });
    } catch (error) {
      return errorResponse(error);
    }
  },
  validator: {
    validate(request): string | null | undefined {
      const entries = [...new URL(request.url).searchParams.entries()];
      if (entries.length > 1 || entries.length === 1 && (entries[0]?.[0] !== "cursor" || !/^[A-Za-z0-9_-]{1,256}$/u.test(entries[0]?.[1] ?? ""))) return undefined;
      return entries[0]?.[1] ?? null;
    },
  },
});

const post = withGatewayRoute(POST_RULE, {
  handler: async ({ value: body }) => {
    if (!body) return state("error", 400);
    try {
      return Response.json(await createBridgeConversation(body.agentId), {
        headers: HEADERS,
        status: 201,
      });
    } catch (error) {
      if (error instanceof BridgeConversationsError && error.code === "agent_id_invalid") return state("error", 400);
      if (error instanceof BridgeConversationsError && error.code === "conversation_not_found") return state("not_found", 404);
      return errorResponse(error);
    }
  },
  validator: { validate: readConversationCreateBody },
});

export async function GET(request: Request) { return get(request); }
export async function POST(request: Request) { return post(request); }
