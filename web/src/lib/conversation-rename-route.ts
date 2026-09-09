import {
  BridgeConversationsError,
  renameBridgeConversation,
  type PublicConversationRenameResult,
} from "./bridge-conversations.ts";
import { readConversationRenameBody } from "./exact-json-body.ts";
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

type Rename = (
  conversationId: string,
  expectedRevision: number,
  title: string,
) => Promise<PublicConversationRenameResult>;
type ConversationContext = { params: Promise<{ conversationId: string }> };
type RenameInput = { conversationId: string; expectedRevision: number; title: string } | null;

const RENAME_RULE = requiredRenameRule();

function requiredRenameRule() {
  const rule = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === "POST" && candidate.path === "/api/conversations/[conversationId]/rename");
  if (!rule) throw new Error("missing gateway manifest rule for POST /api/conversations/[conversationId]/rename");
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
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

export function createConversationRenameHandler({
  gatewayPort,
  rename = renameBridgeConversation,
}: Readonly<{ gatewayPort?: string; rename?: Rename }> = {}) {
  return withGatewayRoute<RenameInput, ConversationContext>(RENAME_RULE, {
    authority: gatewayPort === undefined ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort }),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try {
        return Response.json(
          await rename(value.conversationId, value.expectedRevision, value.title),
          { headers: HEADERS },
        );
      } catch (error) {
        return failure(error);
      }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const body = await readConversationRenameBody(request);
        if (!body) return null;
        const { conversationId } = await context.params;
        return { conversationId, expectedRevision: body.expectedRevision, title: body.title };
      },
    },
  });
}
