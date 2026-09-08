import { AgentSetupBridgeError, requestBridgeAgentSetup } from "./bridge-agent-setup.ts";
import type { AgentSetupAction } from "./agent-setup-contract.ts";
import { readAgentSetupBody } from "./exact-json-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

const HEADERS = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
const failure = (status: string, code: number) => Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
export function createAgentSetupHandler(action: AgentSetupAction, { gatewayPort = process.env.PORT, execute = requestBridgeAgentSetup }: { gatewayPort?: string; execute?: typeof requestBridgeAgentSetup } = {}) {
  return async (request: Request) => {
    const decision = evaluateRequestBoundary({ expectedPort: parseGatewayPort(gatewayPort), host: request.headers.get("host"), method: request.method, origin: request.headers.get("origin"), secFetchSite: request.headers.get("sec-fetch-site") });
    if (!decision.allowed) return failure("forbidden", 403);
    if (request.method !== "POST" || new URL(request.url).search) return failure("invalid", 400);
    const body = await readAgentSetupBody(request, action); if (!body) return failure("invalid", 400);
    try { return Response.json(await execute(action, body), { headers: HEADERS, status: 200 }); }
    catch (error) { const code = error instanceof AgentSetupBridgeError ? error.code : "error"; return failure(code, { invalid: 400, conflict: 409, unavailable: 503, error: 502 }[code]); }
  };
}
