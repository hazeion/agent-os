import {
  BridgeConversationsError,
  fetchBridgeConversationHistory,
  type PublicConversationHistory,
} from "./bridge-conversations.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

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
  gatewayPort = process.env.PORT,
}: Readonly<{ fetchHistory?: FetchHistory; gatewayPort?: string }> = {}) {
  return async function getConversationHistory(request: Request) {
    const decision = evaluateRequestBoundary({
      expectedPort: parseGatewayPort(gatewayPort),
      host: request.headers.get("host"),
      method: request.method,
      origin: request.headers.get("origin"),
      secFetchSite: request.headers.get("sec-fetch-site"),
    });
    if (!decision.allowed) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
    const entries = [...new URL(request.url).searchParams.entries()];
    if (new Set(entries.map(([key]) => key)).size !== entries.length) return fixed("invalid", 400);
    if (entries.some(([key]) => !["state", "q", "cursor"].includes(key))) return fixed("invalid", 400);
    const parameters = new URLSearchParams(entries);
    const state = parameters.get("state");
    const query = parameters.get("q");
    const cursor = parameters.get("cursor");
    if (
      !state
      || !["all", "active", "archived"].includes(state)
      || query !== null && (query.trim() !== query || [...query].length < 1 || [...query].length > 160 || /\p{C}/u.test(query))
      || cursor !== null && !/^[A-Za-z0-9_-]{1,512}$/u.test(cursor)
    ) return fixed("invalid", 400);
    try {
      return Response.json(
        await fetchHistory(state as "all" | "active" | "archived", query, cursor),
        { headers: HEADERS },
      );
    } catch (error) {
      return failure(error);
    }
  };
}
