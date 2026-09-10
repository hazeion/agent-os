import {
  archiveBridgeConversation,
  BridgeConversationsError,
  type PublicConversationArchiveResult,
} from "./bridge-conversations.ts";
import { readExpectedRevisionBody } from "./exact-json-body.ts";
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

type Mutate = (
  conversationId: string,
  expectedRevision: number,
  archived: boolean,
) => Promise<PublicConversationArchiveResult>;
type ConversationContext = { params: Promise<{ conversationId: string }> };
type ArchiveInput = { conversationId: string; expectedRevision: number } | null;

const ARCHIVE_RULE = requiredRule("/api/conversations/[conversationId]/archive");
const RESTORE_RULE = requiredRule("/api/conversations/[conversationId]/restore");

function requiredRule(path: string) {
  const rule = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === "POST" && candidate.path === path);
  if (!rule) throw new Error(`missing gateway manifest rule for POST ${path}`);
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

export function createConversationArchiveHandler(
  archived: boolean,
  {
    gatewayPort,
    mutate = archiveBridgeConversation,
  }: Readonly<{ gatewayPort?: string; mutate?: Mutate }> = {},
) {
  return withGatewayRoute<ArchiveInput, ConversationContext>(archived ? ARCHIVE_RULE : RESTORE_RULE, {
    authority: gatewayPort === undefined ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort }),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try {
        return Response.json(
          await mutate(value.conversationId, value.expectedRevision, archived),
          { headers: HEADERS, status: 200 },
        );
      } catch (error) {
        return failure(error);
      }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const body = await readExpectedRevisionBody(request);
        if (!body) return null;
        const { conversationId } = await context.params;
        return { conversationId, expectedRevision: body.expectedRevision };
      },
    },
  });
}
