const LOOPBACK_HOSTS = new Set(["127.0.0.1", "::1", "localhost"]);
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const SAFE_FETCH_SITES = new Set(["", "same-origin", "none"]);

export type BoundaryInput = {
  expectedPort: number;
  host: string | null;
  method: string;
  origin: string | null;
  secFetchSite: string | null;
};

export type BoundaryDecision =
  | { allowed: true }
  | { allowed: false; reason: "host" | "origin" | "port" | "site" };

type Authority = {
  hostname: string;
  port: number;
};

function parseHost(value: string | null): Authority | null {
  const raw = value?.trim() ?? "";
  if (!raw || /[\s/@?#]/u.test(raw)) return null;
  try {
    const parsed = new URL(`http://${raw}`);
    if (parsed.username || parsed.password || parsed.pathname !== "/") return null;
    const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
    const port = parsed.port ? Number(parsed.port) : 80;
    if (!LOOPBACK_HOSTS.has(hostname) || !Number.isSafeInteger(port)) return null;
    return { hostname, port };
  } catch {
    return null;
  }
}

function parseOrigin(value: string): Authority | null {
  try {
    const parsed = new URL(value);
    if (
      parsed.protocol !== "http:"
      || parsed.username
      || parsed.password
      || parsed.pathname !== "/"
      || parsed.search
      || parsed.hash
    ) {
      return null;
    }
    const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
    const port = parsed.port ? Number(parsed.port) : 80;
    if (!LOOPBACK_HOSTS.has(hostname) || !Number.isSafeInteger(port)) return null;
    return { hostname, port };
  } catch {
    return null;
  }
}

export function parseGatewayPort(value: string | undefined): number {
  const port = Number(value ?? "3000");
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) return 3000;
  return port;
}

export function evaluateRequestBoundary(input: BoundaryInput): BoundaryDecision {
  const host = parseHost(input.host);
  if (!host) return { allowed: false, reason: "host" };
  if (host.port !== input.expectedPort) return { allowed: false, reason: "port" };

  const fetchSite = input.secFetchSite?.trim().toLowerCase() ?? "";
  if (!SAFE_FETCH_SITES.has(fetchSite)) {
    return { allowed: false, reason: "site" };
  }

  const rawOrigin = input.origin?.trim() ?? "";
  if (!rawOrigin) {
    return SAFE_METHODS.has(input.method.toUpperCase())
      ? { allowed: true }
      : { allowed: false, reason: "origin" };
  }
  if (rawOrigin.toLowerCase() === "null") return { allowed: false, reason: "origin" };
  const origin = parseOrigin(rawOrigin);
  if (!origin || origin.hostname !== host.hostname || origin.port !== host.port) {
    return { allowed: false, reason: "origin" };
  }
  return { allowed: true };
}
