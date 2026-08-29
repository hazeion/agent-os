import type { AttachmentCapableAgent } from "./bridge-agent-attachments";

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;
const AGENT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const CAPABILITY = /^[a-z][a-z0-9_.-]{0,63}$/u;

export class PublicAgentAttachmentsError extends Error {
  readonly code: string;
  constructor(code: string) { super(code); this.code = code; this.name = "PublicAgentAttachmentsError"; }
}

function validCapabilities(value: unknown): value is string[] { return Array.isArray(value) && value.length <= 64 && value.every((item) => typeof item === "string" && CAPABILITY.test(item)) && value.every((item, index) => index === 0 || value[index - 1] < item); }

export async function enableAgentAttachments(agentId: string, expectedCapabilities: string[], fetcher: FetchLike = fetch): Promise<AttachmentCapableAgent> {
  if (!AGENT_ID.test(agentId) || !validCapabilities(expectedCapabilities)) throw new PublicAgentAttachmentsError("invalid");
  let response: Response;
  try { response = await fetcher(`/api/agents/${encodeURIComponent(agentId)}/attachments/enable`, { method: "POST", cache: "no-store", redirect: "error", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_capabilities: expectedCapabilities }) }); } catch { throw new PublicAgentAttachmentsError("unavailable"); }
  if (response.headers.get("content-type")?.toLowerCase() !== "application/json") throw new PublicAgentAttachmentsError("invalid_response");
  let value: unknown; try { value = await response.json(); } catch { throw new PublicAgentAttachmentsError("invalid_response"); }
  if (!response.ok) { const status = value && typeof value === "object" && !Array.isArray(value) && typeof (value as Record<string, unknown>).status === "string" ? (value as Record<string, unknown>).status as string : "invalid_response"; throw new PublicAgentAttachmentsError(status); }
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join(",") !== "agent,runtime,schema_version,service,status") throw new PublicAgentAttachmentsError("invalid_response");
  const payload = value as Record<string, unknown>; const agent = payload.agent;
  if (payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || !agent || typeof agent !== "object" || Array.isArray(agent) || Object.keys(agent).sort().join(",") !== "capabilities,id,name,runtime_type,system_role") throw new PublicAgentAttachmentsError("invalid_response");
  const item = agent as Record<string, unknown>;
  if (item.id !== agentId || typeof item.name !== "string" || !item.name || [...item.name].length > 120 || item.name.trim() !== item.name || item.runtime_type !== "hermes" || item.system_role !== null && item.system_role !== "direct" || !validCapabilities(item.capabilities) || !item.capabilities.includes("run.attachments")) throw new PublicAgentAttachmentsError("invalid_response");
  return { id: agentId, name: item.name, runtime_type: "hermes", system_role: item.system_role as "direct" | null, capabilities: [...item.capabilities] };
}

export async function readAgentAttachmentsEnableStatus(agentId: string, fetcher: FetchLike = fetch): Promise<"active_run" | "available" | "enabled" | "unsupported"> {
  if (!AGENT_ID.test(agentId)) throw new PublicAgentAttachmentsError("invalid");
  let response: Response;
  try { response = await fetcher(`/api/agents/${encodeURIComponent(agentId)}/attachments/enable`, { method: "GET", cache: "no-store", redirect: "error" }); } catch { throw new PublicAgentAttachmentsError("unavailable"); }
  if (response.headers.get("content-type")?.toLowerCase() !== "application/json") throw new PublicAgentAttachmentsError("invalid_response");
  let value: unknown; try { value = await response.json(); } catch { throw new PublicAgentAttachmentsError("invalid_response"); }
  if (!response.ok) { const status = value && typeof value === "object" && !Array.isArray(value) && typeof (value as Record<string, unknown>).status === "string" ? (value as Record<string, unknown>).status as string : "invalid_response"; throw new PublicAgentAttachmentsError(status); }
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join(",") !== "agent_id,runtime,schema_version,service,state,status") throw new PublicAgentAttachmentsError("invalid_response");
  const payload = value as Record<string, unknown>;
  if (payload.schema_version !== 1 || payload.service !== "mentat-local-bridge" || payload.runtime !== "python" || payload.status !== "ready" || payload.agent_id !== agentId || !new Set(["active_run", "available", "enabled", "unsupported"]).has(String(payload.state))) throw new PublicAgentAttachmentsError("invalid_response");
  return payload.state as "active_run" | "available" | "enabled" | "unsupported";
}
