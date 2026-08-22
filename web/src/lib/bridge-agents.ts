export const PUBLIC_AGENTS_PATH = "/api/agents";
const PRIVATE_BRIDGE_AGENTS_PATH = "/bridge/v1/agents";
const MAXIMUM_BRIDGE_RESPONSE_BYTES = 1_048_576;
const MAXIMUM_AGENTS = 128;

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: globalThis.RequestInit,
) => Promise<globalThis.Response>;

type BridgeEnvironment = Readonly<Record<string, string | undefined>>;

export type PublicAgent = {
  capabilities: string[];
  id: string;
  name: string;
  runtime_config_id: string;
  runtime_type: string;
};

export type PublicBridgeAgents = {
  agents: PublicAgent[];
  count: number;
  runtime: "python";
  schema_version: 1;
  service: "mentat-local-bridge";
  status: "ready";
};

export class BridgeAgentsError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "BridgeAgentsError";
  }
}

function loadBridgeConfiguration(
  environment: BridgeEnvironment = process.env,
): { origin: string; token: string } {
  const rawOrigin = environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? "";
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let parsed: URL;
  try {
    parsed = new URL(rawOrigin);
  } catch {
    throw new BridgeAgentsError("bridge_configuration_invalid");
  }
  const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  if (
    parsed.protocol !== "http:"
    || !new Set(["127.0.0.1", "::1"]).has(hostname)
    || !parsed.port
    || parsed.username
    || parsed.password
    || parsed.pathname !== "/"
    || parsed.search
    || parsed.hash
    || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)
  ) {
    throw new BridgeAgentsError("bridge_configuration_invalid");
  }
  return { origin: parsed.origin, token };
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u.test(value);
}

function isPublicAgent(value: unknown): value is PublicAgent {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const agent = value as Record<string, unknown>;
  const keys = Object.keys(agent).sort();
  if (keys.join(",") !== "capabilities,id,name,runtime_config_id,runtime_type") return false;
  return (
    isOpaqueId(agent.id)
    && typeof agent.name === "string"
    && agent.name.trim() === agent.name
    && agent.name.length >= 1
    && agent.name.length <= 120
    && !agent.name.includes("\0")
    && typeof agent.runtime_type === "string"
    && /^[a-z][a-z0-9_-]{0,31}$/u.test(agent.runtime_type)
    && isOpaqueId(agent.runtime_config_id)
    && Array.isArray(agent.capabilities)
    && agent.capabilities.length <= 64
    && agent.capabilities.every((capability) => (
      typeof capability === "string" && /^[a-z][a-z0-9_.-]{0,63}$/u.test(capability)
    ))
    && agent.capabilities.every((capability, index, capabilities) => (
      index === 0 || capabilities[index - 1] < capability
    ))
  );
}

function validateReadyPayload(value: unknown): PublicBridgeAgents {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
  const payload = value as Record<string, unknown>;
  const keys = Object.keys(payload).sort();
  if (
    keys.join(",") !== "agents,count,runtime,schema_version,service,status"
    || payload.schema_version !== 1
    || payload.service !== "mentat-local-bridge"
    || payload.runtime !== "python"
    || payload.status !== "ready"
    || !Array.isArray(payload.agents)
    || payload.agents.length > MAXIMUM_AGENTS
    || !Number.isInteger(payload.count)
    || payload.count !== payload.agents.length
    || !payload.agents.every(isPublicAgent)
    || new Set(payload.agents.map((agent) => agent.id)).size !== payload.agents.length
  ) {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
  return {
    agents: payload.agents.map((agent) => ({
      capabilities: [...agent.capabilities],
      id: agent.id,
      name: agent.name,
      runtime_config_id: agent.runtime_config_id,
      runtime_type: agent.runtime_type,
    })),
    count: payload.count,
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
  };
}

function validateFixedState(value: unknown, expected: "unsupported" | "unavailable" | "error"): void {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
  const payload = value as Record<string, unknown>;
  if (
    Object.keys(payload).sort().join(",") !== "runtime,schema_version,service,status"
    || payload.schema_version !== 1
    || payload.service !== "mentat-local-bridge"
    || payload.runtime !== "python"
    || payload.status !== expected
  ) {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
}

function validateRouteNotFound(value: unknown): void {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
  const payload = value as Record<string, unknown>;
  if (
    Object.keys(payload).join(",") !== "error"
    || payload.error !== "bridge_route_not_found"
  ) {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
}

async function readBoundedResponse(response: Response): Promise<string> {
  const declaredLength = response.headers.get("content-length");
  if (
    declaredLength
    && (!/^\d{1,10}$/u.test(declaredLength) || Number(declaredLength) > MAXIMUM_BRIDGE_RESPONSE_BYTES)
  ) {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAXIMUM_BRIDGE_RESPONSE_BYTES) {
        await reader.cancel();
        throw new BridgeAgentsError("bridge_response_invalid");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
}

function parseJson(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
}

export async function fetchBridgeAgents(
  fetcher: FetchLike = fetch,
  environment: BridgeEnvironment = process.env,
): Promise<PublicBridgeAgents> {
  const configuration = loadBridgeConfiguration(environment);
  let response: Response;
  try {
    response = await fetcher(
      new URL(PRIVATE_BRIDGE_AGENTS_PATH, configuration.origin),
      {
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "X-Mentat-Bridge-Token": configuration.token,
        },
        method: "GET",
        redirect: "error",
        signal: AbortSignal.timeout(1500),
      },
    );
  } catch {
    throw new BridgeAgentsError("bridge_unavailable");
  }
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.startsWith("application/json")) {
    throw new BridgeAgentsError("bridge_response_invalid");
  }
  const payload = parseJson(await readBoundedResponse(response));
  if (response.status === 200) return validateReadyPayload(payload);
  if (response.status === 404) {
    validateRouteNotFound(payload);
    throw new BridgeAgentsError("bridge_unsupported");
  }
  if (response.status === 501) {
    validateFixedState(payload, "unsupported");
    throw new BridgeAgentsError("bridge_unsupported");
  }
  if (response.status === 503) {
    validateFixedState(payload, "unavailable");
    throw new BridgeAgentsError("bridge_unavailable");
  }
  if (response.status === 500) {
    validateFixedState(payload, "error");
  }
  throw new BridgeAgentsError("bridge_response_invalid");
}
