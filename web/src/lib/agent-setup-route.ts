import { AgentSetupBridgeError, requestBridgeAgentSetup } from "./bridge-agent-setup.ts";
import type { AgentSetupAction } from "./agent-setup-contract.ts";
import { readAgentSetupBody } from "./exact-json-body.ts";
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "./gateway-route-manifest.ts";
import { withGatewayRoute } from "./gateway-request-context.ts";

const HEADERS = { "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY" };
const failure = (status: string, code: number) => Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
function route(path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === "POST" && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for POST ${path}`);
  return found;
}
const RULES: Readonly<Record<AgentSetupAction, GatewayRouteRule>> = Object.freeze({
  check: route("/api/agent-setup/check"),
  confirm: route("/api/agent-setup/confirm"),
  preview: route("/api/agent-setup/preview"),
});
function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}
export function createAgentSetupHandler(action: AgentSetupAction, { gatewayPort = process.env.PORT, execute = requestBridgeAgentSetup }: { gatewayPort?: string; execute?: typeof requestBridgeAgentSetup } = {}) {
  return withGatewayRoute<Record<string, unknown> | null>(RULES[action], {
    authority: authorityFor(gatewayPort),
    forbidden: () => failure("forbidden", 403),
    handler: async ({ value }) => {
      if (!value) return failure("invalid", 400);
      try { return Response.json(await execute(action, value), { headers: HEADERS, status: 200 }); }
      catch (error) { const code = error instanceof AgentSetupBridgeError ? error.code : "error"; return failure(code, { invalid: 400, conflict: 409, unavailable: 503, error: 502 }[code]); }
    },
    validator: { async validate(request) {
      return new URL(request.url).search ? null : readAgentSetupBody(request, action);
    } },
  });
}
