export const PUBLIC_PROVIDER_CONNECTIONS_PATH = "/api/provider-connections";
const PRIVATE_PATH = "/bridge/v1/provider-connections";
const MAXIMUM_RESPONSE_BYTES = 65_536;

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: globalThis.RequestInit,
) => Promise<globalThis.Response>;
type Environment = Readonly<Record<string, string | undefined>>;

export type PublicProviderCapability = {
  id: "ai.gateway" | "sandbox.readiness" | "connect.token";
  status: "credential_present" | "needs_auth" | "disconnected";
};

export type PublicProviderConnection = {
  capabilities: PublicProviderCapability[];
  id: "connection_vercel";
  label: string;
  model: string;
  provider: "vercel";
  state: "configured" | "needs_auth" | "disconnected";
};

export type PublicBridgeProviderConnections = {
  connections: PublicProviderConnection[];
  count: number;
  runtime: "python";
  schema_version: 1;
  service: "mentat-local-bridge";
  status: "ready";
};

export class BridgeProviderConnectionsError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "BridgeProviderConnectionsError";
  }
}

function configuration(environment: Environment): { origin: string; token: string } {
  let origin: URL;
  try {
    origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? "");
  } catch {
    throw new BridgeProviderConnectionsError("bridge_configuration_invalid");
  }
  const hostname = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  if (
    origin.protocol !== "http:"
    || !new Set(["127.0.0.1", "::1"]).has(hostname)
    || !origin.port
    || origin.username
    || origin.password
    || origin.pathname !== "/"
    || origin.search
    || origin.hash
    || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)
  ) {
    throw new BridgeProviderConnectionsError("bridge_configuration_invalid");
  }
  return { origin: origin.origin, token };
}

function isCapability(value: unknown): value is PublicProviderCapability {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const capability = value as Record<string, unknown>;
  return (
    Object.keys(capability).sort().join(",") === "id,status"
    && new Set(["ai.gateway", "sandbox.readiness", "connect.token"]).has(String(capability.id))
    && new Set(["credential_present", "needs_auth", "disconnected"]).has(String(capability.status))
  );
}

function isConnection(value: unknown): value is PublicProviderConnection {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const connection = value as Record<string, unknown>;
  if (
    Object.keys(connection).sort().join(",") !== "capabilities,id,label,model,provider,state"
    || connection.id !== "connection_vercel"
    || connection.provider !== "vercel"
    || typeof connection.label !== "string"
    || connection.label.trim() !== connection.label
    || connection.label.length < 1
    || connection.label.length > 80
    || /[\u0000-\u001f\u007f]/u.test(connection.label)
    || typeof connection.model !== "string"
    || !/^[A-Za-z0-9][A-Za-z0-9._:+@/-]{1,159}$/u.test(connection.model)
    || !connection.model.includes("/")
    || connection.model.includes("//")
    || !new Set(["configured", "needs_auth", "disconnected"]).has(String(connection.state))
    || !Array.isArray(connection.capabilities)
    || connection.capabilities.length < 1
    || connection.capabilities.length > 3
    || !connection.capabilities.every(isCapability)
  ) return false;
  const order = new Map([
    ["ai.gateway", 0],
    ["sandbox.readiness", 1],
    ["connect.token", 2],
  ]);
  if (
    connection.capabilities[0].id !== "ai.gateway"
    || connection.capabilities.some((capability, index, all) => (
      index > 0 && (order.get(all[index - 1].id) ?? 99) >= (order.get(capability.id) ?? -1)
    ))
  ) return false;
  const gatewayStatus = connection.capabilities[0].status;
  return (
    (connection.state === "configured" && gatewayStatus === "credential_present")
    || (connection.state === "needs_auth" && gatewayStatus === "needs_auth")
    || (
      connection.state === "disconnected"
      && connection.capabilities.every((capability) => capability.status === "disconnected")
    )
  );
}

function ready(value: unknown): PublicBridgeProviderConnections {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new BridgeProviderConnectionsError("bridge_response_invalid");
  }
  const payload = value as Record<string, unknown>;
  if (
    Object.keys(payload).sort().join(",") !== "connections,count,runtime,schema_version,service,status"
    || payload.schema_version !== 1
    || payload.service !== "mentat-local-bridge"
    || payload.runtime !== "python"
    || payload.status !== "ready"
    || !Array.isArray(payload.connections)
    || payload.connections.length > 1
    || !Number.isInteger(payload.count)
    || payload.count !== payload.connections.length
    || !payload.connections.every(isConnection)
  ) {
    throw new BridgeProviderConnectionsError("bridge_response_invalid");
  }
  return {
    connections: payload.connections.map((connection) => ({
      capabilities: connection.capabilities.map((capability) => ({ ...capability })),
      id: connection.id,
      label: connection.label,
      model: connection.model,
      provider: connection.provider,
      state: connection.state,
    })),
    count: payload.count as number,
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
  };
}

function fixed(value: unknown, state: "unsupported" | "unavailable" | "error"): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  return (
    Object.keys(payload).sort().join(",") === "runtime,schema_version,service,status"
    && payload.schema_version === 1
    && payload.service === "mentat-local-bridge"
    && payload.runtime === "python"
    && payload.status === state
  );
}

async function bounded(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES)) {
    throw new BridgeProviderConnectionsError("bridge_response_invalid");
  }
  if (!response.body) throw new BridgeProviderConnectionsError("bridge_response_invalid");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      total += result.value.byteLength;
      if (total > MAXIMUM_RESPONSE_BYTES) {
        await reader.cancel();
        throw new BridgeProviderConnectionsError("bridge_response_invalid");
      }
      chunks.push(result.value);
    }
  } finally {
    reader.releaseLock();
  }
  const raw = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    raw.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  } catch {
    throw new BridgeProviderConnectionsError("bridge_response_invalid");
  }
}

export async function fetchBridgeProviderConnections(
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicBridgeProviderConnections> {
  const bridge = configuration(environment);
  let response: Response;
  try {
    response = await fetcher(new URL(PRIVATE_PATH, bridge.origin), {
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "X-Mentat-Bridge-Token": bridge.token,
      },
      method: "GET",
      redirect: "error",
      signal: AbortSignal.timeout(1_500),
    });
  } catch {
    throw new BridgeProviderConnectionsError("bridge_unavailable");
  }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new BridgeProviderConnectionsError("bridge_response_invalid");
  }
  const payload = await bounded(response);
  if (response.status === 200) return ready(payload);
  if (
    response.status === 404
    && payload
    && typeof payload === "object"
    && !Array.isArray(payload)
    && Object.keys(payload).join(",") === "error"
    && (payload as Record<string, unknown>).error === "bridge_route_not_found"
  ) throw new BridgeProviderConnectionsError("bridge_unsupported");
  if (response.status === 501 && fixed(payload, "unsupported")) {
    throw new BridgeProviderConnectionsError("bridge_unsupported");
  }
  if (response.status === 503 && fixed(payload, "unavailable")) {
    throw new BridgeProviderConnectionsError("bridge_unavailable");
  }
  if (response.status === 500 && fixed(payload, "error")) {
    throw new BridgeProviderConnectionsError("bridge_response_invalid");
  }
  throw new BridgeProviderConnectionsError("bridge_response_invalid");
}
