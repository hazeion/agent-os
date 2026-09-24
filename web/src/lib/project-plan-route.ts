import { projectPlanCapability, ProjectPlanBridgeError } from "./bridge-project-plans.ts";
import { PROJECT_PLAN_JSON_LIMIT, projectPlanRequest, type ProjectPlanOperation } from "./project-plan-contract.ts";
import { PLANNING_HEADERS, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";

export const PROJECT_PLAN_ROUTES = {
  project: ["GET", "/api/projects/[projectId]/plan", { project_id: "projectId" }],
  version: ["GET", "/api/projects/[projectId]/plan/[versionId]", { project_id: "projectId", version_id: "versionId" }],
  publish: ["POST", "/api/projects/[projectId]/plan", { project_id: "projectId" }],
} as const;
type RouteName = keyof typeof PROJECT_PLAN_ROUTES;
type Params = { params: Promise<Record<string, string>> };

async function jsonBody(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > PROJECT_PLAN_JSON_LIMIT)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > PROJECT_PLAN_JSON_LIMIT) { await reader.cancel(); return null; } chunks.push(next.value); } } catch { await reader.cancel().catch(() => undefined); return null; } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; } catch { return null; }
}

export function createProjectPlanHandler(name: RouteName, { capability = projectPlanCapability, gatewayPort = process.env.PORT }: Readonly<{ capability?: typeof projectPlanCapability; gatewayPort?: string }> = {}) {
  const [method, path, parameters] = PROJECT_PLAN_ROUTES[name];
  const operation: ProjectPlanOperation = name;
  return withPlanningGatewayRoute<Record<string, unknown> | null, Params>(method, path, gatewayPort, {
    validator: { async validate(request, _context, routeContext) {
      if (new URL(request.url).search) return null;
      const value = method === "GET" ? {} : await jsonBody(request);
      if (!value) return null;
      const params = await routeContext.params;
      for (const [field, parameter] of Object.entries(parameters)) {
        if (field in value || typeof params[parameter] !== "string") return null;
        value[field] = params[parameter];
      }
      try { return projectPlanRequest(operation, value); } catch { return null; }
    } },
    handler: async ({ value }) => {
      if (!value) return planningFixed("invalid", 400);
      try { return Response.json(await capability(operation, value), { headers: PLANNING_HEADERS }); }
      catch (error) { return error instanceof ProjectPlanBridgeError ? planningFixed(error.code, error.status) : planningFixed("unavailable", 503); }
    },
  });
}
