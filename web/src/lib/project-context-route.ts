import { projectContextCapability, ProjectContextBridgeError } from "./bridge-project-context.ts";
import { CONTEXT_JSON_LIMIT, CONTEXT_UPLOAD_LIMIT, contextRequest, type ContextOperation } from "./project-context-contract.ts";
import { PLANNING_HEADERS, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";

export const PROJECT_CONTEXT_ROUTES = {
  project: ["GET", "/api/projects/[projectId]/context", { project_id: "projectId" }],
  publish: ["POST", "/api/projects/[projectId]/context", { project_id: "projectId" }],
  upload: ["POST", "/api/projects/[projectId]/context/files", { project_id: "projectId" }],
  "staged-file": ["GET", "/api/projects/[projectId]/context/files/[attachmentId]", { project_id: "projectId", attachment_id: "attachmentId" }],
  discard: ["DELETE", "/api/projects/[projectId]/context/files/[attachmentId]", { project_id: "projectId", attachment_id: "attachmentId" }],
  history: ["GET", "/api/project-context/history", {}],
  version: ["GET", "/api/project-context/[contextId]", { context_id: "contextId" }],
  file: ["GET", "/api/project-context/[contextId]/files/[attachmentId]", { context_id: "contextId", attachment_id: "attachmentId" }],
  "grant-preview": ["POST", "/api/project-context/[contextId]/grant/preview", { context_id: "contextId" }],
  "grant-confirm": ["POST", "/api/project-context/[contextId]/grant", { context_id: "contextId" }],
  revoke: ["POST", "/api/projects/[projectId]/context/revoke", { project_id: "projectId" }],
  "prune-preview": ["POST", "/api/project-context/[contextId]/prune/preview", { context_id: "contextId" }],
  "prune-confirm": ["POST", "/api/project-context/[contextId]/prune", { context_id: "contextId" }],
} as const;
type RouteName = keyof typeof PROJECT_CONTEXT_ROUTES;
type Params = { params: Promise<Record<string, string>> };
async function jsonBody(request: Request, maximum: number): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let total = 0;
  try {
    for (;;) { const next = await reader.read(); if (next.done) break; total += next.value.byteLength; if (total > maximum) { await reader.cancel(); return null; } chunks.push(next.value); }
  } catch { await reader.cancel().catch(() => undefined); return null; } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; } catch { return null; }
}
export function createProjectContextHandler(name: RouteName, { capability = projectContextCapability, gatewayPort = process.env.PORT }: Readonly<{ capability?: typeof projectContextCapability; gatewayPort?: string }> = {}) {
  const [method, path, parameters] = PROJECT_CONTEXT_ROUTES[name];
  const operation: ContextOperation = name === "staged-file" ? "file" : name;
  return withPlanningGatewayRoute<Record<string, unknown> | null, Params>(method, path, gatewayPort, {
    validator: { async validate(request, _context, routeContext) {
      if (new URL(request.url).search) return null;
      const value = method === "GET" ? {} : await jsonBody(request, name === "upload" ? CONTEXT_UPLOAD_LIMIT : CONTEXT_JSON_LIMIT);
      if (!value) return null;
      const params = await routeContext.params;
      for (const [field, parameter] of Object.entries(parameters)) {
        if (field in value || typeof params[parameter] !== "string") return null;
        value[field] = params[parameter];
      }
      try { return contextRequest(operation, value); } catch { return null; }
    } },
    handler: async ({ value }) => {
      if (!value) return planningFixed("invalid", 400);
      try {
        if (operation === "file") {
          const result = await capability("file", value);
          const bytes = Buffer.from(result.content_base64, "base64");
          const filename = encodeURIComponent(result.file.name).replace(/['()*]/gu, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
          return new Response(bytes, { headers: { ...PLANNING_HEADERS,
            "Content-Type": result.file.kind === "image" ? result.file.mime_type : "text/plain; charset=utf-8",
            "Content-Length": String(bytes.length), "Content-Disposition": `attachment; filename="project-file"; filename*=UTF-8''${filename}`,
            "Content-Security-Policy": "default-src 'none'; sandbox; frame-ancestors 'none'",
          } });
        }
        return Response.json(await capability(operation, value), { headers: PLANNING_HEADERS });
      } catch (error) {
        return error instanceof ProjectContextBridgeError ? planningFixed(error.code, error.status) : planningFixed("unavailable", 503);
      }
    },
  });
}
