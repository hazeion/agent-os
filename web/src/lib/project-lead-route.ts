import { projectLeadCapability, ProjectLeadBridgeError } from "./bridge-project-leads.ts";
import { projectLeadRequest, type LeadOperation } from "./project-lead-contract.ts";
import { PLANNING_HEADERS, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";

type Params = { params: Promise<{ projectId: string }> };
export function createProjectLeadHandler(operation: LeadOperation, { capability = projectLeadCapability, gatewayPort = process.env.PORT }: Readonly<{ capability?: typeof projectLeadCapability; gatewayPort?: string }> = {}) {
  const method = operation === "project" ? "GET" : "POST";
  return withPlanningGatewayRoute<Record<string, unknown> | null, Params>(method, "/api/projects/[projectId]/lead", gatewayPort, {
    validator: { async validate(request, _context, routeContext) {
      if (new URL(request.url).search) return null;
      let value: Record<string, unknown> = {};
      if (operation === "select") {
        if (request.headers.get("content-type")?.toLowerCase() !== "application/json") return null;
        const declared = request.headers.get("content-length");
        if (declared && (!/^\d{1,5}$/u.test(declared) || Number(declared) > 4096)) return null;
        if (!request.body) return null;
        const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
        try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > 4096) { await reader.cancel(); return null; } chunks.push(next.value); } } catch { return null; } finally { reader.releaseLock(); }
        const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
        let raw: string; try { raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes); } catch { return null; }
        try { const parsed: unknown = JSON.parse(raw); if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null; value = parsed as Record<string, unknown>; } catch { return null; }
      }
      if ("project_id" in value) return null;
      value.project_id = (await routeContext.params).projectId;
      try { return projectLeadRequest(operation, value); } catch { return null; }
    } },
    handler: async ({ value }) => {
      if (!value) return planningFixed("invalid", 400);
      try { return Response.json(await capability(operation, value), { headers: PLANNING_HEADERS }); }
      catch (error) { return error instanceof ProjectLeadBridgeError ? planningFixed(error.code, error.status) : planningFixed("unavailable", 503); }
    },
  });
}
