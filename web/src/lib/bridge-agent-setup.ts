import { parseAgentSetupResult, validAgentSetupBody, type AgentSetupAction, type AgentSetupResult } from "./agent-setup-contract.ts";

export class AgentSetupBridgeError extends Error {
  constructor(readonly code: "invalid" | "conflict" | "unavailable" | "error") { super(code); }
}
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
export async function requestBridgeAgentSetup(action: AgentSetupAction, body: Record<string, unknown>, fetcher: FetchLike = fetch, environment: Readonly<Record<string, string | undefined>> = process.env): Promise<AgentSetupResult> {
  if (!["check", "preview", "confirm"].includes(action) || !validAgentSetupBody(action, body)) throw new AgentSetupBridgeError("invalid");
  let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN ?? ""); } catch { throw new AgentSetupBridgeError("unavailable"); }
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new AgentSetupBridgeError("unavailable");
  let response: Response;
  try { response = await fetcher(new URL(`/bridge/v1/agent-setup/${action}`, origin), { method: "POST", cache: "no-store", redirect: "error", headers: { Accept: "application/json", "Content-Type": "application/json", "X-Mentat-Bridge-Token": token }, body: JSON.stringify(body), signal: AbortSignal.timeout(15_000) }); } catch { throw new AgentSetupBridgeError("unavailable"); }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || !response.body) throw new AgentSetupBridgeError("error");
  const declared = response.headers.get("content-length");
  if (declared !== null && (!/^\d{1,5}$/u.test(declared) || Number(declared) > 4096)) throw new AgentSetupBridgeError("error");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > 4096) { await reader.cancel(); throw new AgentSetupBridgeError("error"); } chunks.push(next.value); }
  } finally { reader.releaseLock(); }
  if (declared !== null && Number(declared) !== size) throw new AgentSetupBridgeError("error");
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let value: unknown; try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { throw new AgentSetupBridgeError("error"); }
  if (response.status !== 200) {
    const state = ({ 400: "invalid", 409: "conflict", 503: "unavailable" } as const)[response.status as 400 | 409 | 503];
    if (state && value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join(",") === "runtime,schema_version,service,status" && (value as Record<string, unknown>).schema_version === 1 && (value as Record<string, unknown>).runtime === "python" && (value as Record<string, unknown>).service === "mentat-local-bridge" && (value as Record<string, unknown>).status === state) throw new AgentSetupBridgeError(state);
    throw new AgentSetupBridgeError("error");
  }
  try { return parseAgentSetupResult(action, value, body.name); } catch { throw new AgentSetupBridgeError("error"); }
}
