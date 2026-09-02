const PRIVATE_ROOT = "/bridge/v1/agents";
const AGENT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const CAPABILITY = /^[a-z][a-z0-9_.-]{0,63}$/u;
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u;
type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
export type TaskCreationAgent = { id: string; name: string; runtime_type: "codex"; system_role: "direct" | null; capabilities: string[] };
export type TaskCreationStatus = "active_run" | "available" | "enabled" | "unsupported";
export class BridgeAgentTaskCreationError extends Error { constructor(readonly code: string) { super(code); } }
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function keys(value: Record<string, unknown>, expected: string) { return Object.keys(value).sort().join(",") === expected; }
function validCapabilities(value: unknown): value is string[] { return Array.isArray(value) && value.length <= 64 && value.every((item) => typeof item === "string" && CAPABILITY.test(item)) && value.every((item, index) => !index || value[index - 1] < item); }
function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? ""; let origin: URL;
  try { origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? ""); } catch { throw new BridgeAgentTaskCreationError("configuration"); }
  const host = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (origin.protocol !== "http:" || !new Set(["127.0.0.1", "::1"]).has(host) || !origin.port || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new BridgeAgentTaskCreationError("configuration");
  return { origin: origin.origin, token };
}
async function read(response: Response): Promise<unknown> {
  if (!response.body || !["application/json", "application/json; charset=utf-8"].includes(response.headers.get("content-type")?.toLowerCase() ?? "")) throw new BridgeAgentTaskCreationError("invalid_response");
  const text = await response.text(); if (text.length > 32_768) throw new BridgeAgentTaskCreationError("invalid_response");
  try { return JSON.parse(text); } catch { throw new BridgeAgentTaskCreationError("invalid_response"); }
}
function failure(response: Response, value: unknown): never {
  if (!record(value) || !keys(value, "runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || typeof value.status !== "string") throw new BridgeAgentTaskCreationError("invalid_response");
  const status = String(value.status); const accepted: Record<number, string[]> = { 400: ["invalid"], 404: ["not_found"], 409: ["conflict"], 415: ["unsupported"], 503: ["unavailable"] };
  if (!accepted[response.status]?.includes(status)) throw new BridgeAgentTaskCreationError("invalid_response");
  throw new BridgeAgentTaskCreationError(status);
}
function agent(value: unknown, agentId: string): TaskCreationAgent {
  if (!record(value) || !keys(value, "agent,runtime,schema_version,service,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || !record(value.agent) || !keys(value.agent, "capabilities,id,name,runtime_type,system_role")) throw new BridgeAgentTaskCreationError("invalid_response");
  const item = value.agent;
  if (item.id !== agentId || !AGENT_ID.test(agentId) || typeof item.name !== "string" || !item.name || item.name.trim() !== item.name || [...item.name].length > 120 || CONTROL.test(item.name) || item.runtime_type !== "codex" || item.system_role !== null && item.system_role !== "direct" || !validCapabilities(item.capabilities) || !item.capabilities.includes("task.create")) throw new BridgeAgentTaskCreationError("invalid_response");
  return { id: agentId, name: item.name, runtime_type: "codex", system_role: item.system_role as "direct" | null, capabilities: [...item.capabilities] };
}
async function request(agentId: string, init: RequestInit, fetcher: FetchLike, environment: Environment) {
  if (!AGENT_ID.test(agentId)) throw new BridgeAgentTaskCreationError("invalid"); const bridge = configuration(environment); let response: Response;
  try { response = await fetcher(new URL(`${PRIVATE_ROOT}/${encodeURIComponent(agentId)}/task-creation/enable`, bridge.origin), { ...init, cache: "no-store", redirect: "error", headers: { Accept: "application/json", "X-Mentat-Bridge-Token": bridge.token, ...(init.headers ?? {}) }, signal: AbortSignal.timeout(5_000) }); } catch { throw new BridgeAgentTaskCreationError("unavailable"); }
  const value = await read(response); if (!response.ok) failure(response, value); return value;
}
export async function enableBridgeAgentTaskCreation(agentId: string, expectedCapabilities: string[], fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<TaskCreationAgent> {
  if (!validCapabilities(expectedCapabilities)) throw new BridgeAgentTaskCreationError("invalid");
  return agent(await request(agentId, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_capabilities: expectedCapabilities }) }, fetcher, environment), agentId);
}
export async function readBridgeAgentTaskCreationStatus(agentId: string, fetcher: FetchLike = fetch, environment: Environment = process.env): Promise<TaskCreationStatus> {
  const value = await request(agentId, { method: "GET" }, fetcher, environment);
  if (!record(value) || !keys(value, "agent_id,runtime,schema_version,service,state,status") || value.schema_version !== 1 || value.service !== "mentat-local-bridge" || value.runtime !== "python" || value.status !== "ready" || value.agent_id !== agentId || !new Set(["active_run", "available", "enabled", "unsupported"]).has(String(value.state))) throw new BridgeAgentTaskCreationError("invalid_response");
  return value.state as TaskCreationStatus;
}
