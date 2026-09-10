import { BridgeAgentAttachmentsError, enableBridgeAgentAttachments, readBridgeAgentAttachmentsEnableStatus, type AgentAttachmentsEnableStatus, type EnableAgentAttachmentsResult } from "./bridge-agent-attachments.ts";
import { readEnableAgentAttachmentsBody } from "./exact-json-body.ts";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "./gateway-route-manifest.ts";
import { withGatewayRoute } from "./gateway-request-context.ts";

const HEADERS = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
const fixed = (status: string, code: number) => Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
function failure(error: unknown) {
  if (!(error instanceof BridgeAgentAttachmentsError)) return fixed("error", 502);
  const map: Record<string, [string, number]> = { bridge_unavailable: ["unavailable", 503], agent_attachments_conflict: ["conflict", 409], agent_attachments_invalid: ["invalid", 400], agent_attachments_not_found: ["not_found", 404], agent_attachments_unsupported: ["unsupported", 415], agent_attachments_unavailable: ["unavailable", 503] };
  const result = map[error.code]; return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}
const ENABLE_PATH = "/api/agents/[agentId]/attachments/enable" as const;
const POST_RULE = route("POST", ENABLE_PATH);
const GET_RULE = route("GET", ENABLE_PATH);
function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}
type AgentContext = { params: Promise<{ agentId: string }> };
type EnableValue = { agentId: string; body: { expectedCapabilities: string[] } } | null;

export function createEnableAgentAttachmentsHandler({ gatewayPort = process.env.PORT, enable = enableBridgeAgentAttachments }: Readonly<{ gatewayPort?: string; enable?: (agentId: string, expectedCapabilities: string[]) => Promise<EnableAgentAttachmentsResult> }> = {}) {
  return withGatewayRoute<EnableValue, AgentContext>(POST_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try { return Response.json(await enable(value.agentId, value.body.expectedCapabilities), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: { async validate(request, _context, context) {
      if (new URL(request.url).search) return null;
      const body = await readEnableAgentAttachmentsBody(request);
      return body ? { agentId: (await context.params).agentId, body } : null;
    } },
  });
}

export function createAgentAttachmentsEnableStatusHandler({ gatewayPort = process.env.PORT, read = readBridgeAgentAttachmentsEnableStatus }: Readonly<{ gatewayPort?: string; read?: (agentId: string) => Promise<AgentAttachmentsEnableStatus> }> = {}) {
  return withGatewayRoute<string | null, AgentContext>(GET_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value }) => {
      if (!value) return fixed("invalid", 400);
      try { return Response.json(await read(value), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: { async validate(request, _context, context) {
      return new URL(request.url).search ? null : (await context.params).agentId;
    } },
  });
}
