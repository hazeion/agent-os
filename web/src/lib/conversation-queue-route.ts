import {
  BridgeConversationsError,
  cancelBridgeConversationTurn,
  continueBridgeConversationTurn,
  editBridgeConversationTurn,
  type PublicConversationQueueMutation,
  type PublicConversationTurnSubmission,
} from "./bridge-conversations.ts";
import { readConversationQueueActionBody } from "./exact-json-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

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
    gatewayPort = process.env.PORT,
    mutate = defaultMutation(action),
  }: Readonly<{ gatewayPort?: string; mutate?: Mutate }> = {},
) {
  return async function postConversationQueueAction(
    request: Request,
    context: { params: Promise<{ conversationId: string; turnId: string }> },
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
    const body = await readConversationQueueActionBody(request, action);
    if (!body) return fixed("invalid", 400);
    const { conversationId, turnId } = await context.params;
    try {
      const result = await mutate(
        conversationId,
        turnId,
        body.expectedRevision,
        body.expectedMessageRevision,
        body.text ?? undefined,
      );
      const status = "run" in result && result.run !== null ? 202 : 200;
      return Response.json(result, { headers: HEADERS, status });
    } catch (error) {
      return failure(error);
    }
  };
}
