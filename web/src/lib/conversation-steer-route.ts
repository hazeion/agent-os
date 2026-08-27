import {
  BridgeConversationsError,
  steerBridgeConversation,
  type PublicConversationSteerResult,
} from "./bridge-conversations.ts";
import { readConversationSteerBody } from "./exact-json-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

type Steer = (
  conversationId: string,
  runId: string,
  text: string,
) => Promise<PublicConversationSteerResult>;

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
    conversation_partial: ["partial", 500],
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

export function createConversationSteerHandler({
  gatewayPort = process.env.PORT,
  steer = steerBridgeConversation,
}: Readonly<{ gatewayPort?: string; steer?: Steer }> = {}) {
  return async function postConversationSteer(
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
    const body = await readConversationSteerBody(request);
    if (!body) return fixed("invalid", 400);
    const { conversationId } = await context.params;
    try {
      return Response.json(
        await steer(conversationId, body.runId, body.text),
        { headers: HEADERS },
      );
    } catch (error) {
      return failure(error);
    }
  };
}
