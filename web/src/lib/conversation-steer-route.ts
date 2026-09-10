import {
  BridgeConversationsError,
  steerBridgeConversation,
  type PublicConversationSteerResult,
} from "./bridge-conversations.ts";
import { readConversationSteerBody } from "./exact-json-body.ts";
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

type Steer = (
  conversationId: string,
  runId: string,
  text: string,
) => Promise<PublicConversationSteerResult>;
type ConversationContext = { params: Promise<{ conversationId: string }> };
type SteerInput = { conversationId: string; runId: string; text: string } | null;

const STEER_RULE = requiredSteerRule();

function requiredSteerRule() {
  const rule = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === "POST" && candidate.path === "/api/conversations/[conversationId]/steer");
  if (!rule) throw new Error("missing gateway manifest rule for POST /api/conversations/[conversationId]/steer");
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
    conversation_conflict: ["conflict", 409],
    conversation_not_found: ["not_found", 404],
    conversation_partial: ["partial", 500],
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

export function createConversationSteerHandler({
  gatewayPort,
  steer = steerBridgeConversation,
}: Readonly<{ gatewayPort?: string; steer?: Steer }> = {}) {
  return withGatewayRoute<SteerInput, ConversationContext>(STEER_RULE, {
    authority: gatewayPort === undefined ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort }),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try {
        return Response.json(
          await steer(value.conversationId, value.runId, value.text),
          { headers: HEADERS },
        );
      } catch (error) {
        return failure(error);
      }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const body = await readConversationSteerBody(request);
        if (!body) return null;
        const { conversationId } = await context.params;
        return { conversationId, runId: body.runId, text: body.text };
      },
    },
  });
}
