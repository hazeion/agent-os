import {
  BridgeConversationsError,
  submitBridgeConversationTurn,
  type PublicConversationTurnSubmission,
} from "./bridge-conversations.ts";
import { readConversationTurnBody } from "./exact-json-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

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
  gatewayPort = process.env.PORT,
  readBody = readConversationTurnBody,
  submitTurn = submitBridgeConversationTurn,
}: Readonly<{
  gatewayPort?: string;
  readBody?: ReadTurnBody;
  submitTurn?: SubmitTurn;
}> = {}) {
  return async function postConversationTurn(
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
    const body = await readBody(request);
    if (!body) return fixed("invalid", 400);
    const { conversationId } = await context.params;
    try {
      const result = await submitTurn(
        conversationId,
        body.text,
        body.idempotencyKey,
      );
      return Response.json(result, {
        headers: HEADERS,
        status: result.duplicate ? 200 : 202,
      });
    } catch (error) {
      return failure(error);
    }
  };
}
