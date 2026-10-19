import { projectInputCapability, ProjectInputBridgeError } from "./bridge-project-planning-inputs.ts";
import { projectInputRequest, type ProjectInputOperation } from "./project-planning-input-contract.ts";
import { PLANNING_HEADERS, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";

type Params = { params: Promise<{ projectId: string; inputId?: string; actionId?: string }> };
const PATHS = { project: "/api/projects/[projectId]/planning-inputs", publish: "/api/projects/[projectId]/planning-inputs", version: "/api/projects/[projectId]/planning-inputs/[inputId]", reconcile: "/api/projects/[projectId]/planning-inputs/actions/[actionId]" } as const;

async function jsonBody(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,6}$/u.test(declared) || Number(declared) > 32768)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > 32768) { await reader.cancel(); return null; } chunks.push(next.value); } }
  catch { await reader.cancel().catch(() => undefined); return null; }
  finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : null; }
  catch { return null; }
}

export function createProjectInputHandler(name: ProjectInputOperation, { capability = projectInputCapability, gatewayPort = process.env.PORT }: Readonly<{ capability?: typeof projectInputCapability; gatewayPort?: string }> = {}) {
  const method = name === "publish" ? "POST" : "GET";
  return withPlanningGatewayRoute<Record<string, unknown> | null, Params>(method, PATHS[name], gatewayPort, {
    validator: { async validate(request, _context, routeContext) {
      const params = await routeContext.params, url = new URL(request.url);
      let value: Record<string, unknown> = {};
      if (name === "publish") { if (url.search) return null; const parsed = await jsonBody(request); if (!parsed || "project_id" in parsed) return null; value = parsed; }
      else if (name === "reconcile") {
        const entries = [...url.searchParams.entries()];
        if (entries.length !== 1 || entries[0][0] !== "scope_token") return null;
        value = { action_id: params.actionId, scope_token: entries[0][1] };
      } else {
        if (url.search) return null;
        if (name === "version") value.input_id = params.inputId;
      }
      value.project_id = params.projectId;
      try { return projectInputRequest(name, value); } catch { return null; }
    } },
    handler: async ({ value }) => {
      if (!value) return planningFixed("invalid", 400);
      try { return Response.json(await capability(name, value), { headers: PLANNING_HEADERS }); }
      catch (error) { return error instanceof ProjectInputBridgeError ? planningFixed(error.code, error.status) : planningFixed("unavailable", 503); }
    },
  });
}
