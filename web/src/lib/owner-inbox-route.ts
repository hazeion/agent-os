import { ownerInboxCapability, OwnerInboxBridgeError } from "./bridge-owner-inbox.ts";
import { inboxRequest, type InboxOperation } from "./owner-inbox-contract.ts";
import { PLANNING_HEADERS, planningFixed, withPlanningGatewayRoute } from "./planning-overview-route.ts";

export const OWNER_INBOX_ROUTES = {
  page: ["GET", "/api/inbox"],
  open: ["GET", "/api/inbox/[itemId]"],
  mark: ["POST", "/api/inbox/[itemId]/mark"],
  preview: ["POST", "/api/inbox/[itemId]/review/preview"],
  confirm: ["POST", "/api/inbox/[itemId]/review/confirm"],
} as const;
type RouteName = keyof typeof OWNER_INBOX_ROUTES;
type Params = { params: Promise<Record<string, string>> };
async function jsonBody(request: Request): Promise<Record<string, unknown> | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d{1,5}$/u.test(declared) || Number(declared) > 4096)) return null;
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > 4096) { await reader.cancel(); return null; } chunks.push(next.value); } } catch { await reader.cancel().catch(() => undefined); return null; } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null; } catch { return null; }
}
export function createOwnerInboxHandler(name: RouteName, { capability = ownerInboxCapability, gatewayPort = process.env.PORT }: Readonly<{ capability?: typeof ownerInboxCapability; gatewayPort?: string }> = {}) {
  const [method, path] = OWNER_INBOX_ROUTES[name];
  const operation: InboxOperation = name;
  return withPlanningGatewayRoute<Record<string, unknown> | null, Params>(method, path, gatewayPort, {
    validator: { async validate(request, _context, routeContext) {
      const url = new URL(request.url);
      if (name !== "page" && url.search) return null;
      let value: Record<string, unknown>;
      if (name === "page") {
        const names = [...url.searchParams.keys()];
        if (names.length < 1 || names.length > 2 || new Set(names).size !== names.length || names.some((field) => field !== "view" && field !== "after") || !url.searchParams.has("view")) return null;
        value = { view: url.searchParams.get("view"), after: url.searchParams.get("after") };
      } else if (method === "GET") value = {};
      else { const body = await jsonBody(request); if (!body) return null; value = body; }
      if (name !== "page") {
        const params = await routeContext.params;
        if ("item_id" in value || typeof params.itemId !== "string") return null;
        value.item_id = params.itemId;
      }
      try { return inboxRequest(operation, value); } catch { return null; }
    } },
    handler: async ({ value }) => {
      if (!value) return planningFixed("invalid", 400);
      try { return Response.json(await capability(operation, value), { headers: PLANNING_HEADERS }); }
      catch (error) { return error instanceof OwnerInboxBridgeError ? planningFixed(error.code, error.status) : planningFixed("unavailable", 503); }
    },
  });
}
