import {
  validAgentConfigurationPayload,
  validAgentConfigurationPreview,
  validAgentConfigurationResult,
  type PublicAgentConfigurationPayload,
  type PublicAgentConfigurationPreview,
  type PublicAgentConfigurationResult,
} from "./bridge-conversations";

const AGENT_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const HEADERS = { Accept: "application/json" };
export const AGENT_CONFIGURATION_READ_PUBLIC_TIMEOUT = 45_000;
export const AGENT_CONFIGURATION_PREVIEW_PUBLIC_TIMEOUT = 75_000;
export const AGENT_CONFIGURATION_CONFIRM_PUBLIC_TIMEOUT = 195_000;

export class PublicAgentConfigurationError extends Error {
  constructor(readonly code: string) { super(code); this.name = "PublicAgentConfigurationError"; }
}

async function request(path: string, init: RequestInit = {}, timeout = AGENT_CONFIGURATION_READ_PUBLIC_TIMEOUT): Promise<{ response: Response; payload: unknown }> {
  try {
    const response = await fetch(path, { ...init, cache: "no-store", headers: { ...HEADERS, ...init.headers }, signal: AbortSignal.timeout(timeout) });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new Error();
    const declared = response.headers.get("content-length");
    if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > 3_000_000)) throw new Error();
    if (!response.body) throw new Error();
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > 3_000_000) { await reader.cancel(); throw new Error(); }
      chunks.push(next.value);
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return { response, payload: JSON.parse(decoded) as unknown };
  } catch (error) {
    if (error instanceof PublicAgentConfigurationError) throw error;
    throw new PublicAgentConfigurationError("unavailable");
  }
}

function failure(response: Response, payload: unknown): never {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new PublicAgentConfigurationError("response_invalid");
  const value = payload as Record<string, unknown>;
  if (Object.keys(value).sort().join(",") !== "schema_version,status" || value.schema_version !== 1) throw new PublicAgentConfigurationError("response_invalid");
  const mapped: Record<string, string> = { conflict: "conflict", error: "error", invalid: "invalid", not_found: "not_found", partial: "partial", unavailable: "unavailable", unsupported: "unsupported" };
  const code = mapped[String(value.status)];
  if (!code || ![400, 404, 409, 501, 502, 503].includes(response.status)) throw new PublicAgentConfigurationError("response_invalid");
  throw new PublicAgentConfigurationError(code);
}

function path(agentId: string, suffix = "") {
  if (!AGENT_ID.test(agentId)) throw new PublicAgentConfigurationError("invalid");
  return `/api/agents/${encodeURIComponent(agentId)}/configuration${suffix}`;
}

export async function fetchAgentConfiguration(agentId: string): Promise<PublicAgentConfigurationPayload> {
  const { response, payload } = await request(path(agentId));
  if (response.status === 200 && validAgentConfigurationPayload(payload)
    && payload.configuration.agent_id === agentId) return structuredClone(payload);
  failure(response, payload);
}

export async function previewAgentConfiguration(agentId: string, provider: string, model: string): Promise<PublicAgentConfigurationPreview> {
  const { response, payload } = await request(path(agentId, "/preview"), { body: JSON.stringify({ provider, model }), headers: { "Content-Type": "application/json" }, method: "POST" }, AGENT_CONFIGURATION_PREVIEW_PUBLIC_TIMEOUT);
  if (response.status === 200 && validAgentConfigurationPreview(payload)
    && payload.agent_id === agentId && payload.target.provider === provider
    && payload.target.model === model) return structuredClone(payload);
  failure(response, payload);
}

export async function confirmAgentConfiguration(agentId: string, provider: string, model: string, confirmationId: string): Promise<PublicAgentConfigurationResult> {
  const { response, payload } = await request(path(agentId), { body: JSON.stringify({ confirmation_id: confirmationId, provider, model }), headers: { "Content-Type": "application/json" }, method: "POST" }, AGENT_CONFIGURATION_CONFIRM_PUBLIC_TIMEOUT);
  if (response.status === 200 && validAgentConfigurationResult(payload)
    && payload.agent_id === agentId && payload.configuration.current.provider === provider
    && payload.configuration.current.model === model) return structuredClone(payload);
  failure(response, payload);
}
