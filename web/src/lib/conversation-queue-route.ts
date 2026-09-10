import {
  BridgeConversationsError,
  cancelBridgeConversationTurn,
  continueBridgeConversationTurn,
  editBridgeConversationTurn,
  type PublicConversationQueueMutation,
  type PublicConversationTurnSubmission,
} from "./bridge-conversations.ts";
import { readConversationQueueActionBody } from "./exact-json-body.ts";
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

type Action = "edit" | "cancel" | "continue";
type Result = PublicConversationQueueMutation | PublicConversationTurnSubmission;
type Mutate = (
  conversationId: string,
  turnId: string,
  expectedRevision: number,
  expectedMessageRevision: number,
  text?: string,
) => Promise<Result>;
type ConversationContext = { params: Promise<{ conversationId: string; turnId: string }> };
type QueueInput = { body: Awaited<ReturnType<typeof readConversationQueueActionBody>>; conversationId: string; turnId: string };

const QUEUE_RULES: Readonly<Record<Action, (typeof GATEWAY_ROUTE_MANIFEST)[number]>> = Object.freeze({
  cancel: requiredRule("/api/conversations/[conversationId]/turns/[turnId]/cancel"),
  continue: requiredRule("/api/conversations/[conversationId]/turns/[turnId]/continue"),
  edit: requiredRule("/api/conversations/[conversationId]/turns/[turnId]/edit"),
});

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
    codex_cli_missing: ["cli_missing", 409],
    codex_sign_in_required: ["sign_in_required", 409],
    conversation_conflict: ["conflict", 409],
    conversation_not_found: ["not_found", 404],
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

function defaultMutation(action: Action): Mutate {
  if (action === "edit") {
    return (conversationId, turnId, expectedRevision, expectedMessageRevision, text) => (
      editBridgeConversationTurn(
        conversationId,
        turnId,
        expectedRevision,
        expectedMessageRevision,
        text ?? "",
      )
    );
  }
  if (action === "cancel") {
    return (conversationId, turnId, expectedRevision, expectedMessageRevision) => (
      cancelBridgeConversationTurn(
        conversationId,
        turnId,
        expectedRevision,
        expectedMessageRevision,
      )
    );
  }
  return (conversationId, turnId, expectedRevision, expectedMessageRevision) => (
    continueBridgeConversationTurn(
      conversationId,
      turnId,
      expectedRevision,
      expectedMessageRevision,
    )
  );
}

export function createConversationQueueActionHandler(
  action: Action,
  {
    gatewayPort,
    mutate = defaultMutation(action),
  }: Readonly<{ gatewayPort?: string; mutate?: Mutate }> = {},
) {
  return withGatewayRoute<QueueInput, ConversationContext>(QUEUE_RULES[action], {
    authority: gatewayPort === undefined ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort }),
    handler: async ({ value }) => {
      if (!value.body) return fixed("invalid", 400);
      try {
        const result = await mutate(
          value.conversationId,
          value.turnId,
          value.body.expectedRevision,
          value.body.expectedMessageRevision,
          value.body.text ?? undefined,
        );
        const status = "run" in result && result.run !== null ? 202 : 200;
        return Response.json(result, { headers: HEADERS, status });
      } catch (error) {
        return failure(error);
      }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return { body: null, conversationId: "", turnId: "" };
        const body = await readConversationQueueActionBody(request, action);
        if (!body) return { body: null, conversationId: "", turnId: "" };
        const { conversationId, turnId } = await context.params;
        return { body, conversationId, turnId };
      },
    },
  });
}
