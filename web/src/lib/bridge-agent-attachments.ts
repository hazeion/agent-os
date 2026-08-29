const PRIVATE_ROOT = "/bridge/v1/agents";
const MAXIMUM_RESPONSE_BYTES = 32 * 1024;

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export type AttachmentCapableAgent = {
  id: string;
  name: string;
  runtime_type: "hermes";
  system_role: "direct" | null;
  capabilities: string[];
};

export type EnableAgentAttachmentsResult = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  agent: AttachmentCapableAgent;
};

export type AgentAttachmentsEnableStatus = {
  schema_version: 1;
  service: "mentat-local-bridge";
  runtime: "python";
  status: "ready";
  agent_id: string;
  state: "active_run" | "available" | "enabled" | "unsupported";
};

export class BridgeAgentAttachmentsError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "BridgeAgentAttachmentsError"; }
}

const AGENT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const CAPABILITY = /^[a-z][a-z0-9_.-]{0,63}$/u;
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u;

function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string): boolean { return Object.keys(value).sort().join(",") === expected; }
function validCapabilities(value: unknown): value is string[] { return Array.isArray(value) && value.length <= 64 && value.every((item) => typeof item === "string" && CAPABILITY.test(item)) && value.every((item, index) => index === 0 || value[index - 1] < item); }

function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? ""; let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgeAgentAttachmentsError("bridge_configuration_invalid"); }
  const host = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(host) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeAgentAttachmentsError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}

async function bytes(response: Response): Promise<Uint8Array> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES)) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  if (!response.body) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > MAXIMUM_RESPONSE_BYTES) { await reader.cancel(); throw new BridgeAgentAttachmentsError("bridge_response_invalid"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const result = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
  if (declared && result.byteLength !== Number(declared)) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  return result;
}

function failure(response: Response, value: unknown): never {
  if (!record(value) || !keys(value, "runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || typeof value.status !== "string") throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  const expected: Record<number, string[]> = { 400: ["invalid"], 404: ["not_found"], 409: ["conflict"], 415: ["unsupported"], 503: ["unavailable"] };
  if (!expected[response.status]?.includes(value.status)) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  throw new BridgeAgentAttachmentsError(`agent_attachments_${value.status}`);
}

function parse(value: unknown, agentId: string): EnableAgentAttachmentsResult {
  if (!record(value) || !keys(value, "agent,runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || !record(value.agent) || !keys(value.agent, "capabilities,id,name,runtime_type,system_role")) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  const agent = value.agent;
  if (agent.id !== agentId || typeof agent.id !== "string" || !AGENT_ID.test(agent.id) || typeof agent.name !== "string" || !agent.name || [...agent.name].length > 120 || agent.name.trim() !== agent.name || CONTROL.test(agent.name) || agent.runtime_type !== "hermes" || agent.system_role !== null && agent.system_role !== "direct" || !validCapabilities(agent.capabilities) || !agent.capabilities.includes("run.attachments")) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  return { ...(value as EnableAgentAttachmentsResult), agent: { ...(agent as AttachmentCapableAgent), capabilities: [...agent.capabilities] } };
}

export async function enableBridgeAgentAttachments(agentId: string, expectedCapabilities: string[], fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<EnableAgentAttachmentsResult> {
  if (!AGENT_ID.test(agentId) || !validCapabilities(expectedCapabilities)) throw new BridgeAgentAttachmentsError("agent_attachments_invalid");
  const bridge = configuration(environment); let response: Response;
  try {
    response = await fetcher(new URL(`${PRIVATE_ROOT}/${encodeURIComponent(agentId)}/attachments/enable`, bridge.origin), { method: "POST", cache: "no-store", redirect: "error", headers: { Accept: "application/json", "Content-Type": "application/json", "X-Mentat-Bridge-Token": bridge.token }, body: JSON.stringify({ expected_capabilities: expectedCapabilities }), signal: AbortSignal.timeout(5_000) });
  } catch { throw new BridgeAgentAttachmentsError("bridge_unavailable"); }
  if (!["application/json", "application/json; charset=utf-8"].includes(response.headers.get("content-type")?.toLowerCase() ?? "")) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  let value: unknown; try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await bytes(response))); } catch (error) { if (error instanceof BridgeAgentAttachmentsError) throw error; throw new BridgeAgentAttachmentsError("bridge_response_invalid"); }
  if (!response.ok) return failure(response, value);
  return parse(value, agentId);
}

export async function readBridgeAgentAttachmentsEnableStatus(agentId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<AgentAttachmentsEnableStatus> {
  if (!AGENT_ID.test(agentId)) throw new BridgeAgentAttachmentsError("agent_attachments_invalid");
  const bridge = configuration(environment); let response: Response;
  try { response = await fetcher(new URL(`${PRIVATE_ROOT}/${encodeURIComponent(agentId)}/attachments/enable`, bridge.origin), { method: "GET", cache: "no-store", redirect: "error", headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token }, signal: AbortSignal.timeout(5_000) }); } catch { throw new BridgeAgentAttachmentsError("bridge_unavailable"); }
  if (!["application/json", "application/json; charset=utf-8"].includes(response.headers.get("content-type")?.toLowerCase() ?? "")) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  let value: unknown; try { value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await bytes(response))); } catch (error) { if (error instanceof BridgeAgentAttachmentsError) throw error; throw new BridgeAgentAttachmentsError("bridge_response_invalid"); }
  if (!response.ok) return failure(response, value);
  if (!record(value) || !keys(value, "agent_id,runtime,schema_version,service,state,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || value.agent_id !== agentId || !new Set(["active_run", "available", "enabled", "unsupported"]).has(String(value.state))) throw new BridgeAgentAttachmentsError("bridge_response_invalid");
  return { ...(value as AgentAttachmentsEnableStatus) };
}
