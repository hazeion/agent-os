import {
  BridgeConversationsError,
  confirmBridgeAgentConfiguration,
  fetchBridgeAgentConfiguration,
  previewBridgeAgentConfiguration,
} from "./bridge-conversations.ts";
import { readAgentConfigurationBody } from "./exact-json-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixed(status: string, code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

function failure(error: unknown) {
  if (!(error instanceof BridgeConversationsError)) return fixed("error", 502);
  const mapped: Record<string, [string, number]> = {
    agent_id_invalid: ["invalid", 400],
    bridge_unavailable: ["unavailable", 503],
    bridge_unsupported: ["unsupported", 501],
    conversation_conflict: ["conflict", 409],
    conversation_not_found: ["not_found", 404],
    conversation_partial: ["partial", 502],
    conversation_request_invalid: ["invalid", 400],
  };
  const result = mapped[error.code];
  return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

function allowed(request: Request, gatewayPort: string | undefined) {
  return evaluateRequestBoundary({
    expectedPort: parseGatewayPort(gatewayPort),
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
  }).allowed;
}

export function createAgentConfigurationHandlers({
  gatewayPort = process.env.PORT,
  read = fetchBridgeAgentConfiguration,
  preview = previewBridgeAgentConfiguration,
  confirm = confirmBridgeAgentConfiguration,
} = {}) {
  return {
    async get(request: Request, context: { params: Promise<{ agentId: string }> }) {
      if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
      if (new URL(request.url).search) return fixed("invalid", 400);
      const { agentId } = await context.params;
      try { return Response.json(await read(agentId), { headers: HEADERS }); }
      catch (error) { return failure(error); }
    },
    async preview(request: Request, context: { params: Promise<{ agentId: string }> }) {
      if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
      if (new URL(request.url).search) return fixed("invalid", 400);
      const body = await readAgentConfigurationBody(request, true);
      if (!body) return fixed("invalid", 400);
      const { agentId } = await context.params;
      try { return Response.json(await preview(agentId, body.provider, body.model), { headers: HEADERS }); }
      catch (error) { return failure(error); }
    },
    async confirm(request: Request, context: { params: Promise<{ agentId: string }> }) {
      if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
      if (new URL(request.url).search) return fixed("invalid", 400);
      const body = await readAgentConfigurationBody(request, false);
      if (!body?.confirmationId) return fixed("invalid", 400);
      const { agentId } = await context.params;
      try { return Response.json(await confirm(agentId, body.provider, body.model, body.confirmationId), { headers: HEADERS }); }
      catch (error) { return failure(error); }
    },
  };
}
