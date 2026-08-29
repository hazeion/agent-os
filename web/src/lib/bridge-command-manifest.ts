import {
  parseCommandManifest,
  PublicCommandManifestError,
  type PublicCommandManifest,
} from "./public-command-manifest.ts";

const PRIVATE_COMMAND_MANIFEST_PATH = "/bridge/v1/agent-console/commands";
const MAXIMUM_RESPONSE_BYTES = 16_384;
const READ_TIMEOUT_MILLISECONDS = 3_500;

type Environment = Readonly<Record<string, string | undefined>>;
type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

export class BridgeCommandManifestError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.code = code;
    this.name = "BridgeCommandManifestError";
  }
}

function configuration(environment: Environment) {
  const token = environment.MENTAT_BRIDGE_TOKEN ?? "";
  let origin: URL;
  try {
    origin = new URL(environment.MENTAT_BRIDGE_ORIGIN?.trim() ?? "");
  } catch {
    throw new BridgeCommandManifestError("bridge_configuration_invalid");
  }
  const hostname = origin.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
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
  ) throw new BridgeCommandManifestError("bridge_configuration_invalid");
  return { origin: origin.origin, token };
}

async function boundedJson(response: Response): Promise<unknown> {
  const declared = response.headers.get("content-length");
  if (declared && (!/^\d{1,10}$/u.test(declared) || Number(declared) > MAXIMUM_RESPONSE_BYTES)) {
    throw new BridgeCommandManifestError("bridge_response_invalid");
  }
  if (!response.body) throw new BridgeCommandManifestError("bridge_response_invalid");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > MAXIMUM_RESPONSE_BYTES) {
        await reader.cancel();
        throw new BridgeCommandManifestError("bridge_response_invalid");
      }
      chunks.push(next.value);
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
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown;
  } catch {
    throw new BridgeCommandManifestError("bridge_response_invalid");
  }
}

function validFailure(value: unknown, status: string): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  return Object.keys(payload).sort().join(",") === "runtime,schema_version,service,status"
    && payload.schema_version === 1
    && payload.service === "mentat-local-bridge"
    && payload.runtime === "python"
    && payload.status === status;
}

export async function fetchBridgeCommandManifest(
  fetcher: FetchLike = fetch,
  environment: Environment = process.env,
): Promise<PublicCommandManifest> {
  const bridge = configuration(environment);
  try {
    const response = await fetcher(new URL(PRIVATE_COMMAND_MANIFEST_PATH, bridge.origin), {
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "X-Mentat-Bridge-Token": bridge.token,
      },
      method: "GET",
      redirect: "error",
      signal: AbortSignal.timeout(READ_TIMEOUT_MILLISECONDS),
    });
    if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      throw new BridgeCommandManifestError("bridge_response_invalid");
    }
    const payload = await boundedJson(response);
    if (response.status !== 200) {
      if (response.status === 503 && validFailure(payload, "unavailable")) {
        throw new BridgeCommandManifestError("bridge_unavailable");
      }
      throw new BridgeCommandManifestError("bridge_response_invalid");
    }
    try {
      return parseCommandManifest(payload);
    } catch (error) {
      if (error instanceof PublicCommandManifestError) {
        throw new BridgeCommandManifestError("bridge_response_invalid");
      }
      throw error;
    }
  } catch (error) {
    if (error instanceof BridgeCommandManifestError) throw error;
    throw new BridgeCommandManifestError("bridge_unavailable");
  }
}
