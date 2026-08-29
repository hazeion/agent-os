import {
  BridgeConversationsError,
  renameBridgeConversation,
  type PublicConversationRenameResult,
} from "./bridge-conversations.ts";
import { readConversationRenameBody } from "./exact-json-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

type Rename = (
  conversationId: string,
  expectedRevision: number,
  title: string,
) => Promise<PublicConversationRenameResult>;

function fixed(status: string, code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

function failure(error: unknown) {
  if (!(error instanceof BridgeConversationsError)) return fixed("error", 502);
  const mapped: Record<string, [string, number]> = {
    bridge_unavailable: ["unavailable", 503],
    bridge_unsupported: ["unsupported", 501],
    conversation_conflict: ["conflict", 409],
    conversation_not_found: ["not_found", 404],
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

export function createConversationRenameHandler({
  gatewayPort = process.env.PORT,
  rename = renameBridgeConversation,
}: Readonly<{ gatewayPort?: string; rename?: Rename }> = {}) {
  return async function postConversationRename(
    request: Request,
    context: { params: Promise<{ conversationId: string }> },
  ) {
    const decision = evaluateRequestBoundary({
      expectedPort: parseGatewayPort(gatewayPort),
      host: request.headers.get("host"),
      method: request.method,
      origin: request.headers.get("origin"),
      secFetchSite: request.headers.get("sec-fetch-site"),
    });
    if (!decision.allowed) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
    if (new URL(request.url).search) return fixed("invalid", 400);
    const body = await readConversationRenameBody(request);
    if (!body) return fixed("invalid", 400);
    const { conversationId } = await context.params;
    try {
      return Response.json(
        await rename(conversationId, body.expectedRevision, body.title),
        { headers: HEADERS },
      );
    } catch (error) {
      return failure(error);
    }
  };
}
