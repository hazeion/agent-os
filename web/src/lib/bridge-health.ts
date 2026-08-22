export const PUBLIC_BRIDGE_HEALTH_PATH = "/api/bridge/health";
const PRIVATE_BRIDGE_HEALTH_PATH = "/bridge/v1/health";
const MAXIMUM_BRIDGE_RESPONSE_BYTES = 4096;

type FetchLike = (
  input: string | URL | globalThis.Request,
  init?: globalThis.RequestInit,
) => Promise<globalThis.Response>;

type BridgeEnvironment = Readonly<Record<string, string | undefined>>;

export type PublicBridgeHealth = {
  mentat_version: string;
  runtime: "python";
  schema_version: 1;
  service: "mentat-local-bridge";
  status: "ready";
};

export type BridgeConfiguration = {
  origin: string;
  token: string;
};

export class BridgeHealthError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "BridgeHealthError";
  }
}

export function loadBridgeConfiguration(
  environment: BridgeEnvironment = process.env,
): BridgeConfiguration {
  const rawOrigin = environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? "";
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let parsed: URL;
  try {
    parsed = new URL(rawOrigin);
  } catch {
    throw new BridgeHealthError("bridge_configuration_invalid");
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
    throw new BridgeHealthError("bridge_configuration_invalid");
  }
  return { origin: parsed.origin, token };
}

function validateBridgePayload(value: unknown): PublicBridgeHealth {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new BridgeHealthError("bridge_response_invalid");
  }
  const payload = value as Record<string, unknown>;
  if (
    payload.schema_version !== 1
    || payload.status !== "ready"
    || payload.service !== "mentat-local-bridge"
    || payload.runtime !== "python"
    || typeof payload.mentat_version !== "string"
    || !/^[A-Za-z0-9._+-]{1,64}$/u.test(payload.mentat_version)
  ) {
    throw new BridgeHealthError("bridge_response_invalid");
  }
  return {
    mentat_version: payload.mentat_version,
    runtime: "python",
    schema_version: 1,
    service: "mentat-local-bridge",
    status: "ready",
  };
}

async function readBoundedResponse(response: Response): Promise<string> {
  const declaredLength = response.headers.get("content-length");
  if (
    declaredLength
    && (!/^\d{1,10}$/u.test(declaredLength) || Number(declaredLength) > MAXIMUM_BRIDGE_RESPONSE_BYTES)
  ) {
    throw new BridgeHealthError("bridge_response_invalid");
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
        throw new BridgeHealthError("bridge_response_invalid");
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
    throw new BridgeHealthError("bridge_response_invalid");
  }
}

export async function fetchBridgeHealth(
  fetcher: FetchLike = fetch,
  environment: BridgeEnvironment = process.env,
): Promise<PublicBridgeHealth> {
  const configuration = loadBridgeConfiguration(environment);
  let response: Response;
  try {
    response = await fetcher(
      new URL(PRIVATE_BRIDGE_HEALTH_PATH, configuration.origin),
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
    throw new BridgeHealthError("bridge_unavailable");
  }
  if (!response.ok || response.status !== 200) {
    throw new BridgeHealthError("bridge_unavailable");
  }
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.startsWith("application/json")) {
    throw new BridgeHealthError("bridge_response_invalid");
  }
  const text = await readBoundedResponse(response);
  try {
    return validateBridgePayload(JSON.parse(text));
  } catch (error) {
    if (error instanceof BridgeHealthError) throw error;
    throw new BridgeHealthError("bridge_response_invalid");
  }
}
