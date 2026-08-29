import { BridgeAgentAttachmentsError, enableBridgeAgentAttachments, readBridgeAgentAttachmentsEnableStatus, type AgentAttachmentsEnableStatus, type EnableAgentAttachmentsResult } from "./bridge-agent-attachments.ts";
import { readEnableAgentAttachmentsBody } from "./exact-json-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

const HEADERS = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
const fixed = (status: string, code: number) => Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
function failure(error: unknown) {
  if (!(error instanceof BridgeAgentAttachmentsError)) return fixed("error", 502);
  const map: Record<string, [string, number]> = { bridge_unavailable: ["unavailable", 503], agent_attachments_conflict: ["conflict", 409], agent_attachments_invalid: ["invalid", 400], agent_attachments_not_found: ["not_found", 404], agent_attachments_unsupported: ["unsupported", 415], agent_attachments_unavailable: ["unavailable", 503] };
  const result = map[error.code]; return result ? fixed(result[0], result[1]) : fixed("error", 502);
}

export function createEnableAgentAttachmentsHandler({ gatewayPort = process.env.PORT, enable = enableBridgeAgentAttachments }: Readonly<{ gatewayPort?: string; enable?: (agentId: string, expectedCapabilities: string[]) => Promise<EnableAgentAttachmentsResult> }> = {}) {
  return async (request: Request, context: { params: Promise<{ agentId: string }> }) => {
    const decision = evaluateRequestBoundary({ expectedPort: parseGatewayPort(gatewayPort), host: request.headers.get("host"), method: request.method, origin: request.headers.get("origin"), secFetchSite: request.headers.get("sec-fetch-site") });
    if (!decision.allowed) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
    if (new URL(request.url).search) return fixed("invalid", 400);
    const body = await readEnableAgentAttachmentsBody(request); if (!body) return fixed("invalid", 400);
    const { agentId } = await context.params;
    try { return Response.json(await enable(agentId, body.expectedCapabilities), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}

export function createAgentAttachmentsEnableStatusHandler({ gatewayPort = process.env.PORT, read = readBridgeAgentAttachmentsEnableStatus }: Readonly<{ gatewayPort?: string; read?: (agentId: string) => Promise<AgentAttachmentsEnableStatus> }> = {}) {
  return async (request: Request, context: { params: Promise<{ agentId: string }> }) => {
    const decision = evaluateRequestBoundary({ expectedPort: parseGatewayPort(gatewayPort), host: request.headers.get("host"), method: request.method, origin: request.headers.get("origin"), secFetchSite: request.headers.get("sec-fetch-site") });
    if (!decision.allowed) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
    if (new URL(request.url).search) return fixed("invalid", 400);
    const { agentId } = await context.params;
    try { return Response.json(await read(agentId), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}
