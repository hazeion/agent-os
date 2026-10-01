import { projectDeliverableCapability, DeliverableBridgeError } from "./bridge-project-deliverables.ts";
import { DELIVERABLE_JSON_LIMIT, deliverableRequest, type DeliverableOperation } from "./project-deliverable-contract.ts";
import { PLANNING_HEADERS, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";

export const PROJECT_DELIVERABLE_ROUTES = {
  project: ["GET", "/api/projects/[projectId]/deliverables", { project_id: "projectId" }],
  publish: ["POST", "/api/projects/[projectId]/deliverables", { project_id: "projectId" }],
  version: ["GET", "/api/projects/[projectId]/deliverables/[versionId]", { project_id: "projectId", version_id: "versionId" }],
  "retired-history": ["GET", "/api/deliverables/history", {}],
  "retired-version": ["GET", "/api/deliverables/[versionId]", { version_id: "versionId" }],
  preview: ["GET", "/api/deliverables/[versionId]/preview", { version_id: "versionId" }],
} as const;
type RouteName = keyof typeof PROJECT_DELIVERABLE_ROUTES;
type Params = { params: Promise<Record<string, string>> };
async function jsonBody(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > DELIVERABLE_JSON_LIMIT)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > DELIVERABLE_JSON_LIMIT) { await reader.cancel(); return null; } chunks.push(next.value); } } catch { await reader.cancel().catch(() => undefined); return null; } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; } catch { return null; }
}
export function createProjectDeliverableHandler(name: RouteName, { capability = projectDeliverableCapability, gatewayPort = process.env.PORT }: Readonly<{ capability?: typeof projectDeliverableCapability; gatewayPort?: string }> = {}) {
  const [method, path, parameters] = PROJECT_DELIVERABLE_ROUTES[name];
  const operation: DeliverableOperation = name;
  return withPlanningGatewayRoute<Record<string, unknown> | null, Params>(method, path, gatewayPort, {
    validator: { async validate(request, _context, routeContext) {
      const url = new URL(request.url);
      if (name !== "retired-history" && url.search || name === "retired-history" && (url.searchParams.size > 1 || !!url.search && !url.searchParams.has("offset") || url.searchParams.has("offset") && (url.searchParams.getAll("offset").length !== 1 || !/^(?:0|50|100|150|200|250)$/u.test(url.searchParams.get("offset") ?? "")))) return null;
      const value = method === "GET" ? name === "retired-history" && url.searchParams.has("offset") ? { offset: Number(url.searchParams.get("offset")) } : {} : await jsonBody(request);
      if (!value) return null;
      const params = await routeContext.params;
      for (const [field, parameter] of Object.entries(parameters)) {
        if (field in value || typeof params[parameter] !== "string") return null;
        value[field] = params[parameter];
      }
      try { return deliverableRequest(operation, value); } catch { return null; }
    } },
    handler: async ({ value }) => {
      if (!value) return planningFixed("invalid", 400);
      try {
        if (operation === "preview") {
          const result = await capability("preview", value);
          const bytes = Buffer.from(result.content_base64, "base64");
          return new Response(bytes, { headers: { ...PLANNING_HEADERS,
            "Content-Type": "image/png", "Content-Length": String(bytes.length),
            "Content-Disposition": "inline; filename=garage-layout.png",
            "Content-Security-Policy": "default-src 'none'; sandbox; frame-ancestors 'none'",
          } });
        }
        return Response.json(await capability(operation, value), { headers: PLANNING_HEADERS });
      } catch (error) {
        return error instanceof DeliverableBridgeError ? planningFixed(error.code, error.status) : planningFixed("unavailable", 503);
      }
    },
  });
}
