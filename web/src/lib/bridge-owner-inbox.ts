import { ownerBridgeHeaders } from "./owner-request-context.ts";
import { inboxRequest, inboxResult, INBOX_JSON_LIMIT, OwnerInboxContractError, type InboxOperation, type InboxResults } from "./owner-inbox-contract.ts";

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type Environment = Readonly<Record<string, string | undefined>>;
const READS = new Set<InboxOperation>(["page", "open"]);
const FAILURES = new Set(["invalid", "stale", "capacity", "incomplete", "confirmation_conflict", "project_unavailable", "unavailable"]);
export class OwnerInboxBridgeError extends Error { constructor(readonly code = "unavailable", readonly status = 503) { super("owner_inbox_bridge_unavailable"); } }
function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL; try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); } catch { throw new OwnerInboxBridgeError(); }
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new OwnerInboxBridgeError();
  return { origin: origin.origin, token };
}
async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > INBOX_JSON_LIMIT)) throw new OwnerInboxContractError();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > INBOX_JSON_LIMIT) { await reader.cancel(); throw new OwnerInboxContractError(); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new OwnerInboxContractError(); }
}
export async function ownerInboxCapability<K extends InboxOperation>(operation: K, input: unknown, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<InboxResults[K]> {
  let request: Record<string, unknown>;
  try { request = inboxRequest(operation, input); } catch { throw new OwnerInboxBridgeError("invalid", 400); }
  const bridge = configuration(environment), read = READS.has(operation);
  const url = new URL(`/bridge/v1/owner-inbox/${operation}`, bridge.origin);
  if (operation === "page") { url.searchParams.set("view", String(request.view)); if (request.after !== null) url.searchParams.set("after", String(request.after)); }
  if (operation === "open") url.searchParams.set("item_id", String(request.item_id));
  try {
    const response = await fetcher(url, { method: read ? "GET" : "POST", ...(read ? {} : { body: JSON.stringify(request) }),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(read ? 15_000 : 35_000),
      headers: { Accept: "application/json", ...(read ? {} : { "Content-Type": "application/json" }), ...ownerBridgeHeaders(), "X-Mentat-Bridge-Token": bridge.token } });
    const payload = await boundedJson(response);
    if (response.status !== 200) {
      if (payload && typeof payload === "object" && !Array.isArray(payload) && Object.keys(payload).sort().join(",") === "schema_version,status"
          && (payload as Record<string, unknown>).schema_version === 1 && typeof (payload as Record<string, unknown>).status === "string") {
        const code = (payload as Record<string, unknown>).status as string;
        if (FAILURES.has(code) && (response.status === 400 && code === "invalid" || response.status === 404 && code === "unavailable" || response.status === 409 && !["invalid", "unavailable"].includes(code) || response.status === 503 && code === "unavailable")) throw new OwnerInboxBridgeError(code, response.status);
      }
      throw new OwnerInboxContractError();
    }
    return inboxResult(operation, payload, request);
  } catch (error) {
    if (error instanceof OwnerInboxBridgeError) throw error;
    throw new OwnerInboxBridgeError(error instanceof OwnerInboxContractError ? "invalid_response" : "unavailable", error instanceof OwnerInboxContractError ? 502 : 503);
  }
}
