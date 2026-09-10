import {
  BridgeConversationsError,
  confirmBridgeAgentConfiguration,
  fetchBridgeAgentConfiguration,
  previewBridgeAgentConfiguration,
} from "./bridge-conversations.ts";
import { readAgentConfigurationBody } from "./exact-json-body.ts";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "./gateway-route-manifest.ts";
import { withGatewayRoute } from "./gateway-request-context.ts";

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

function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}

const GET_RULE = route("GET", "/api/agents/[agentId]/configuration");
const PREVIEW_RULE = route("POST", "/api/agents/[agentId]/configuration/preview");
const CONFIRM_RULE = route("POST", "/api/agents/[agentId]/configuration");

function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}
type AgentContext = { params: Promise<{ agentId: string }> };
type ConfigurationBody = { confirmationId: string | null; model: string; provider: string };
type AgentValue = { agentId: string } | null;
type ConfigurationValue = { agentId: string; body: ConfigurationBody } | null;
type ConfirmationValue = { agentId: string; body: ConfigurationBody & { confirmationId: string } } | null;

export function createAgentConfigurationHandlers({
  gatewayPort = process.env.PORT,
  read = fetchBridgeAgentConfiguration,
  preview = previewBridgeAgentConfiguration,
  confirm = confirmBridgeAgentConfiguration,
} = {}) {
  const authority = authorityFor(gatewayPort);
  return {
    get: withGatewayRoute<AgentValue, AgentContext>(GET_RULE, {
      authority,
      handler: async ({ value }) => {
        if (!value) return fixed("invalid", 400);
        try { return Response.json(await read(value.agentId), { headers: HEADERS }); }
        catch (error) { return failure(error); }
      },
      validator: { async validate(request, _context, context) {
        if (new URL(request.url).search) return null;
        return { agentId: (await context.params).agentId };
      } },
    }),
    preview: withGatewayRoute<ConfigurationValue, AgentContext>(PREVIEW_RULE, {
      authority,
      handler: async ({ value }) => {
        if (!value) return fixed("invalid", 400);
        try { return Response.json(await preview(value.agentId, value.body.provider, value.body.model), { headers: HEADERS }); }
        catch (error) { return failure(error); }
      },
      validator: { async validate(request, _context, context) {
        if (new URL(request.url).search) return null;
        const body = await readAgentConfigurationBody(request, true);
        return body ? { agentId: (await context.params).agentId, body } : null;
      } },
    }),
    confirm: withGatewayRoute<ConfirmationValue, AgentContext>(CONFIRM_RULE, {
      authority,
      handler: async ({ value }) => {
        if (!value) return fixed("invalid", 400);
        try { return Response.json(await confirm(value.agentId, value.body.provider, value.body.model, value.body.confirmationId), { headers: HEADERS }); }
        catch (error) { return failure(error); }
      },
      validator: { async validate(request, _context, context) {
        if (new URL(request.url).search) return null;
        const body = await readAgentConfigurationBody(request, false);
        return body?.confirmationId ? { agentId: (await context.params).agentId, body: { ...body, confirmationId: body.confirmationId } } : null;
      } },
    }),
  };
}
