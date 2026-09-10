import {
  BridgeConversationsError,
  resumeBridgeConversationRun,
  retryBridgeConversationRun,
  type PublicConversationRunAttemptResult,
} from "./bridge-conversations.ts";
import { readConversationRunAttemptBody } from "./exact-json-body.ts";
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

type Retry = (conversationId: string, sourceRunId: string, key: string) => Promise<PublicConversationRunAttemptResult>;
type ConversationContext = { params: Promise<{ conversationId: string }> };
type RetryInput = { conversationId: string; idempotencyKey: string; sourceRunId: string } | null;

const RETRY_RULE = requiredRule("/api/conversations/[conversationId]/retry");
const RESUME_RULE = requiredRule("/api/conversations/[conversationId]/resume");

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
    conversation_active_run: ["active_run", 409],
    conversation_capacity_unavailable: ["capacity_unavailable", 409],
    conversation_conflict: ["conflict", 409],
    conversation_idempotency_conflict: ["idempotency_conflict", 409],
    conversation_not_found: ["not_found", 404],
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

function createConversationRunAttemptHandler(
  rule: typeof RETRY_RULE,
  retry: Retry,
  gatewayPort: string | undefined,
) {
  return withGatewayRoute<RetryInput, ConversationContext>(rule, {
    authority: gatewayPort === undefined ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort }),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try {
        const result = await retry(value.conversationId, value.sourceRunId, value.idempotencyKey);
        return Response.json(result, { headers: HEADERS, status: result.duplicate ? 200 : 202 });
      } catch (error) { return failure(error); }
    },
    validator: {
      async validate(request, _approved, context) {
        if (new URL(request.url).search) return null;
        const body = await readConversationRunAttemptBody(request);
        if (!body) return null;
        const { conversationId } = await context.params;
        return { conversationId, idempotencyKey: body.idempotencyKey, sourceRunId: body.sourceRunId };
      },
    },
  });
}

export function createConversationRetryHandler({
  gatewayPort,
  retry = retryBridgeConversationRun,
}: Readonly<{ gatewayPort?: string; retry?: Retry }> = {}) {
  return createConversationRunAttemptHandler(RETRY_RULE, retry, gatewayPort);
}

export function createConversationResumeHandler({
  gatewayPort,
  retry = resumeBridgeConversationRun,
}: Readonly<{ gatewayPort?: string; retry?: Retry }> = {}) {
  return createConversationRunAttemptHandler(RESUME_RULE, retry, gatewayPort);
}
