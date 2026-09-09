import {
  BridgeConversationsError,
  fetchBridgeConversationHistory,
  type PublicConversationHistory,
} from "./bridge-conversations.ts";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST } from "./gateway-route-manifest.ts";
import { withGatewayRoute } from "./gateway-request-context.ts";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

type FetchHistory = (
  state: "all" | "active" | "archived",
  query: string | null,
  cursor: string | null,
) => Promise<PublicConversationHistory>;
type HistoryInput = { cursor: string | null; query: string | null; state: "all" | "active" | "archived" } | null;

const HISTORY_RULE = requiredHistoryRule();

function requiredHistoryRule() {
  const rule = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === "GET" && candidate.path === "/api/conversation-history");
  if (!rule) throw new Error("missing gateway manifest rule for GET /api/conversation-history");
  return rule;
}

function fixed(status: string, code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

function failure(error: unknown) {
  if (!(error instanceof BridgeConversationsError)) return fixed("error", 502);
  const mapped: Record<string, [string, number]> = {
    bridge_unavailable: ["unavailable", 503],
    bridge_unsupported: ["unsupported", 501],
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

export function createConversationHistoryHandler({
  fetchHistory = fetchBridgeConversationHistory,
  gatewayPort,
}: Readonly<{ fetchHistory?: FetchHistory; gatewayPort?: string }> = {}) {
  return withGatewayRoute<HistoryInput>(HISTORY_RULE, {
    authority: gatewayPort === undefined ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort }),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try {
        return Response.json(
          await fetchHistory(value.state, value.query, value.cursor),
          { headers: HEADERS },
        );
      } catch (error) {
        return failure(error);
      }
    },
    validator: {
      validate(request) {
        const entries = [...new URL(request.url).searchParams.entries()];
        if (new Set(entries.map(([key]) => key)).size !== entries.length) return null;
        if (entries.some(([key]) => !["state", "q", "cursor"].includes(key))) return null;
        const parameters = new URLSearchParams(entries);
        const state = parameters.get("state");
        const query = parameters.get("q");
        const cursor = parameters.get("cursor");
        if (
          !state
          || !["all", "active", "archived"].includes(state)
          || query !== null && (query.trim() !== query || [...query].length < 1 || [...query].length > 160 || /\p{C}/u.test(query))
          || cursor !== null && !/^[A-Za-z0-9_-]{1,512}$/u.test(cursor)
        ) return null;
        return { cursor, query, state: state as "all" | "active" | "archived" };
      },
    },
  });
}
