import {
  BridgeConversationsError,
  submitBridgeConversationTurn,
  type PublicConversationTurnSubmission,
} from "./bridge-conversations.ts";
import { readConversationTurnBody } from "./exact-json-body.ts";
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

type FailureState =
  | "active_run"
  | "capacity_unavailable"
  | "cli_missing"
  | "error"
  | "idempotency_conflict"
  | "invalid"
  | "not_found"
  | "sign_in_required"
  | "unavailable"
  | "unsupported";

type SubmitTurn = (
  conversationId: string,
  text: string,
  idempotencyKey: string,
) => Promise<PublicConversationTurnSubmission>;

type ReadTurnBody = typeof readConversationTurnBody;
type ConversationContext = { params: Promise<{ conversationId: string }> };
type TurnInput = { conversationId: string; idempotencyKey: string; text: string } | null;

const TURN_RULE = requiredTurnRule();

function requiredTurnRule() {
  const rule = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === "POST" && candidate.path === "/api/conversations/[conversationId]/turns");
  if (!rule) throw new Error("missing gateway manifest rule for POST /api/conversations/[conversationId]/turns");
  return rule;
}

function fixed(status: FailureState, code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

function failure(error: unknown) {
  if (!(error instanceof BridgeConversationsError)) return fixed("error", 502);
  const mapped: Record<string, [FailureState, number]> = {
    bridge_unavailable: ["unavailable", 503],
    bridge_unsupported: ["unsupported", 501],
    codex_cli_missing: ["cli_missing", 409],
    codex_sign_in_required: ["sign_in_required", 409],
    conversation_active_run: ["active_run", 409],
    conversation_capacity_unavailable: ["capacity_unavailable", 409],
    conversation_idempotency_conflict: ["idempotency_conflict", 409],
    conversation_not_found: ["not_found", 404],
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

export function createConversationTurnPostHandler({
  gatewayPort,
  readBody = readConversationTurnBody,
  submitTurn = submitBridgeConversationTurn,
}: Readonly<{
  gatewayPort?: string;
  readBody?: ReadTurnBody;
  submitTurn?: SubmitTurn;
}> = {}) {
  return withGatewayRoute<TurnInput, ConversationContext>(TURN_RULE, {
    authority: gatewayPort === undefined ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort }),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try {
        const result = await submitTurn(
          value.conversationId,
          value.text,
          value.idempotencyKey,
        );
        return Response.json(result, {
          headers: HEADERS,
          status: result.duplicate ? 200 : 202,
        });
      } catch (error) {
        return failure(error);
      }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const body = await readBody(request);
        if (!body) return null;
        const { conversationId } = await context.params;
        return { conversationId, idempotencyKey: body.idempotencyKey, text: body.text };
      },
    },
  });
}
