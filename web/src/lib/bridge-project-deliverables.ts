import { createHash } from "node:crypto";
import { ownerBridgeHeaders } from "./owner-request-context.ts";
import { DELIVERABLE_PREVIEW_LIMIT, DELIVERABLE_READS, DeliverableContractError, deliverableRequest, deliverableResult, type DeliverableOperation, type DeliverableResults } from "./project-deliverable-contract.ts";

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
type Environment = Readonly<Record<string, string | undefined>>;
const FAILURES = new Set(["invalid", "revision_conflict", "source_changed", "project_changed", "task_changed", "version_unavailable", "project_unavailable", "capacity", "inbox_capacity", "content_invalid", "content_capacity", "preview_unavailable", "preview_capacity", "link_invalid", "slot_invalid", "revision_invalid", "incomplete", "stale", "confirmation_conflict", "unavailable"]);
export class DeliverableBridgeError extends Error { constructor(readonly code = "unavailable", readonly status = 503) { super("deliverable_bridge_unavailable"); } }
function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL; try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); } catch { throw new DeliverableBridgeError(); }
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new DeliverableBridgeError();
  return { origin: origin.origin, token };
}
async function boundedJson(response: Response, maximum: number): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > maximum)) throw new DeliverableContractError();
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > maximum) { await reader.cancel(); throw new DeliverableContractError(); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; } catch { throw new DeliverableContractError(); }
}
export async function projectDeliverableCapability<K extends DeliverableOperation>(operation: K, input: unknown, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<DeliverableResults[K]> {
  let request: Record<string, unknown>;
  try { request = deliverableRequest(operation, input); } catch { throw new DeliverableBridgeError("invalid", 400); }
  const bridge = configuration(environment), read = DELIVERABLE_READS.has(operation);
  const url = new URL(`/bridge/v1/project-deliverables/${operation}`, bridge.origin);
  if (read) for (const [key, value] of Object.entries(request)) url.searchParams.set(key, String(value));
  try {
    const response = await fetcher(url, { method: read ? "GET" : "POST", ...(read ? {} : { body: JSON.stringify(request) }),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(read ? 15_000 : 35_000),
      headers: { Accept: "application/json", ...(read ? {} : { "Content-Type": "application/json" }), ...ownerBridgeHeaders(), "X-Mentat-Bridge-Token": bridge.token } });
    const raw = await boundedJson(response, operation === "preview" ? DELIVERABLE_PREVIEW_LIMIT : 512 * 1024);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new DeliverableContractError();
    const payload = raw as Record<string, unknown>;
    if (response.status !== 200) {
      if (Object.keys(payload).sort().join(",") !== "schema_version,status" || payload.schema_version !== 1 || typeof payload.status !== "string" || !FAILURES.has(payload.status)) throw new DeliverableContractError();
      if (response.status === 400 && payload.status === "invalid" || response.status === 404 && payload.status === "project_unavailable" || response.status === 409 && payload.status !== "invalid" && payload.status !== "unavailable" || response.status === 503 && payload.status === "unavailable") throw new DeliverableBridgeError(payload.status, response.status);
      throw new DeliverableContractError();
    }
    if (Object.keys(payload).sort().join(",") !== "data,runtime,schema_version,service,status" || payload.schema_version !== 1 || payload.runtime !== "python" || payload.service !== "mentat-local-bridge" || payload.status !== "ready") throw new DeliverableContractError();
    const result = deliverableResult(operation, payload.data, request);
    if (operation === "preview") {
      const image = result as DeliverableResults["preview"];
      const bytes = Buffer.from(image.content_base64, "base64");
      const pngSignature = [137, 80, 78, 71, 13, 10, 26, 10];
      if (bytes.length !== image.byte_size || bytes.toString("base64") !== image.content_base64 || !pngSignature.every((value, index) => bytes[index] === value) || createHash("sha256").update(bytes).digest("hex") !== image.sha256) throw new DeliverableContractError();
    }
    return result;
  } catch (error) {
    if (error instanceof DeliverableBridgeError) throw error;
    throw new DeliverableBridgeError(error instanceof DeliverableContractError ? "invalid_response" : "unavailable", error instanceof DeliverableContractError ? 502 : 503);
  }
}
