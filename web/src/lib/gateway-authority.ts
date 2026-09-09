import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "./gateway-route-manifest.ts";

/**
 * Process-owned gateway admission policy. MDA-4B initially exposes only the
 * existing local profile; a remote profile cannot be selected from a request.
 */
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "::1", "localhost"]);
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const SAFE_FETCH_SITES = new Set(["", "same-origin", "none"]);
const LOCAL_MODE = "local";

export type GatewayAuthorityInput = Readonly<{ expectedPort: number; host: string | null; method: string; origin: string | null; secFetchSite: string | null }>;
export type GatewayAuthorityRequest = Readonly<{ host: string | null; method: string; origin: string | null; pathname: string; secFetchSite: string | null }>;
export type GatewayAuthorityDecision = Readonly<{ allowed: true }> | Readonly<{ allowed: false; reason: "host" | "origin" | "port" | "site" }>;
export type GatewayRouteDecision = GatewayAuthorityDecision & Readonly<{ route: GatewayRouteRule | null }>;
export type GatewayAuthority = Readonly<{ authorize(request: GatewayAuthorityRequest): GatewayRouteDecision; mode: "local" }>;
type Authority = Readonly<{ hostname: string; port: number }>;
type GatewayEnvironment = Readonly<Record<string, string | undefined>>;

export class GatewayAuthorityStartupError extends Error {
  constructor(message = "remote gateway activation is unavailable") {
    super(message);
    this.name = "GatewayAuthorityStartupError";
  }
}

function parseHost(value: string | null): Authority | null {
  const raw = value?.trim() ?? "";
  if (!raw || /[\s/@?#]/u.test(raw)) return null;
  try {
    const parsed = new URL(`http://${raw}`);
    if (parsed.username || parsed.password || parsed.pathname !== "/") return null;
    const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
    const port = parsed.port ? Number(parsed.port) : 80;
    return LOOPBACK_HOSTS.has(hostname) && Number.isSafeInteger(port) ? { hostname, port } : null;
  } catch { return null; }
}

function parseOrigin(value: string): Authority | null {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) return null;
    const hostname = parsed.hostname.toLowerCase().replace(/^\[|\]$/gu, "");
    const port = parsed.port ? Number(parsed.port) : 80;
    return LOOPBACK_HOSTS.has(hostname) && Number.isSafeInteger(port) ? { hostname, port } : null;
  } catch { return null; }
}

export function parseGatewayPort(value: string | undefined): number {
  const port = Number(value ?? "3000");
  return Number.isSafeInteger(port) && port >= 1 && port <= 65535 ? port : 3000;
}

type RouteSegment = Readonly<{ kind: "literal"; value: string }> | Readonly<{ kind: "parameter" }> | Readonly<{ kind: "catchall"; optional: boolean }>;

function routeSegments(template: string): RouteSegment[] {
  const parts = template.split("/").slice(1);
  return parts.map((part, index) => {
    if (/^\[\.\.\.[^\]]+\]$/u.test(part)) {
      if (index !== parts.length - 1) throw new GatewayAuthorityStartupError(`gateway catchall must be final: ${template}`);
      return { kind: "catchall", optional: false };
    }
    if (/^\[\[\.\.\.[^\]]+\]\]$/u.test(part)) {
      if (index !== parts.length - 1) throw new GatewayAuthorityStartupError(`gateway catchall must be final: ${template}`);
      return { kind: "catchall", optional: true };
    }
    return /^\[[^\]]+\]$/u.test(part) ? { kind: "parameter" } : { kind: "literal", value: part };
  });
}

function matchRoutePath(template: string, pathname: string): boolean {
  if (!pathname.startsWith("/")) return false;
  const expected = routeSegments(template);
  const actual = pathname.split("/").slice(1);
  const catchall = expected.at(-1);
  const fixed = catchall?.kind === "catchall" ? expected.slice(0, -1) : expected;
  if (actual.length < fixed.length || (catchall?.kind !== "catchall" && actual.length !== fixed.length)) return false;
  if (!fixed.every((segment, index) => segment.kind === "literal" ? actual[index] === segment.value : actual[index]!.length > 0)) return false;
  return catchall?.kind !== "catchall" || catchall.optional || actual.length > fixed.length;
}

type RouteSpecificity = readonly [literalSegments: number, fixedSegments: number, requiredCatchall: number, catchallPenalty: number];

function routeSpecificity(template: string): RouteSpecificity {
  const segments = routeSegments(template);
  const catchall = segments.at(-1);
  const fixed = catchall?.kind === "catchall" ? segments.slice(0, -1) : segments;
  return [
    fixed.filter((segment) => segment.kind === "literal").length,
    fixed.length,
    catchall?.kind === "catchall" && !catchall.optional ? 1 : 0,
    catchall?.kind === "catchall" ? -1 : 0,
  ];
}

function compareSpecificity(left: RouteSpecificity, right: RouteSpecificity): number {
  for (let index = 0; index < left.length; index += 1) {
    const difference = left[index]! - right[index]!;
    if (difference) return difference;
  }
  return 0;
}

function routeTemplatesOverlap(left: string, right: string): boolean {
  const leftSegments = routeSegments(left);
  const rightSegments = routeSegments(right);
  const leftCatchall = leftSegments.at(-1);
  const rightCatchall = rightSegments.at(-1);
  const leftFixed = leftCatchall?.kind === "catchall" ? leftSegments.slice(0, -1) : leftSegments;
  const rightFixed = rightCatchall?.kind === "catchall" ? rightSegments.slice(0, -1) : rightSegments;
  const leftMinimum = leftFixed.length + (leftCatchall?.kind === "catchall" && !leftCatchall.optional ? 1 : 0);
  const rightMinimum = rightFixed.length + (rightCatchall?.kind === "catchall" && !rightCatchall.optional ? 1 : 0);
  const leftMaximum = leftCatchall?.kind === "catchall" ? Number.POSITIVE_INFINITY : leftFixed.length;
  const rightMaximum = rightCatchall?.kind === "catchall" ? Number.POSITIVE_INFINITY : rightFixed.length;
  if (Math.max(leftMinimum, rightMinimum) > Math.min(leftMaximum, rightMaximum)) return false;
  return leftFixed.slice(0, Math.min(leftFixed.length, rightFixed.length)).every((segment, index) => {
    const other = rightFixed[index]!;
    return segment.kind !== "literal" || other.kind !== "literal" || segment.value === other.value;
  });
}

/** Fail process startup rather than selecting between equally-specific overlapping operations. */
export function validateGatewayRouteManifest(manifest: readonly GatewayRouteRule[] = GATEWAY_ROUTE_MANIFEST): void {
  for (let left = 0; left < manifest.length; left += 1) {
    for (let right = left + 1; right < manifest.length; right += 1) {
      const first = manifest[left]!;
      const second = manifest[right]!;
      if (
        first.method === second.method
        && compareSpecificity(routeSpecificity(first.path), routeSpecificity(second.path)) === 0
        && routeTemplatesOverlap(first.path, second.path)
      ) throw new GatewayAuthorityStartupError(`ambiguous gateway route manifest: ${first.method} ${first.path} and ${second.path}`);
    }
  }
}

export function matchGatewayRoute(pathname: string, method: string, manifest: readonly GatewayRouteRule[] = GATEWAY_ROUTE_MANIFEST): GatewayRouteRule | null {
  const normalizedMethod = method.toUpperCase();
  const directMatches = manifest.filter((rule) => rule.method === normalizedMethod && matchRoutePath(rule.path, pathname));
  // Next implements HEAD through an exact GET handler when that route has no
  // explicit HEAD export. Keep explicit static HEAD rules authoritative, then
  // preserve the framework's local API fallback without widening other methods.
  const matches = directMatches.length || normalizedMethod !== "HEAD"
    ? directMatches
    : manifest.filter((rule) => rule.method === "GET" && matchRoutePath(rule.path, pathname));
  if (!matches.length) return null;
  const highestSpecificity = matches.reduce((highest, rule) => compareSpecificity(routeSpecificity(rule.path), routeSpecificity(highest.path)) > 0 ? rule : highest);
  const mostSpecific = matches.filter((rule) => compareSpecificity(routeSpecificity(rule.path), routeSpecificity(highestSpecificity.path)) === 0);
  return mostSpecific.length === 1 ? mostSpecific[0]! : null;
}

/** Local-only compatibility authority; do not add a request-selected mode. */
export function evaluateGatewayAuthority(input: GatewayAuthorityInput): GatewayAuthorityDecision {
  const host = parseHost(input.host);
  if (!host) return { allowed: false, reason: "host" };
  if (host.port !== input.expectedPort) return { allowed: false, reason: "port" };
  const fetchSite = input.secFetchSite?.trim().toLowerCase() ?? "";
  if (!SAFE_FETCH_SITES.has(fetchSite)) return { allowed: false, reason: "site" };
  const rawOrigin = input.origin?.trim() ?? "";
  if (!rawOrigin) return SAFE_METHODS.has(input.method.toUpperCase()) ? { allowed: true } : { allowed: false, reason: "origin" };
  if (rawOrigin.toLowerCase() === "null") return { allowed: false, reason: "origin" };
  const origin = parseOrigin(rawOrigin);
  return !origin || origin.hostname !== host.hostname || origin.port !== host.port ? { allowed: false, reason: "origin" } : { allowed: true };
}

/** The port is process configuration, captured once before any request is admitted. */
export function createGatewayAuthority(environment: GatewayEnvironment): GatewayAuthority {
  validateGatewayRouteManifest();
  const configuredMode = environment.MENTAT_GATEWAY_MODE?.trim().toLowerCase() ?? "";
  if (configuredMode && configuredMode !== LOCAL_MODE) {
    throw new GatewayAuthorityStartupError("only the local gateway mode is available");
  }
  const expectedPort = parseGatewayPort(environment.PORT);
  return Object.freeze({
    authorize(request: GatewayAuthorityRequest): GatewayRouteDecision {
      const decision = evaluateGatewayAuthority({ ...request, expectedPort });
      return decision.allowed ? { allowed: true, route: matchGatewayRoute(request.pathname, request.method) } : { ...decision, route: null };
    },
    mode: "local" as const,
  });
}

/**
 * This is the only authority used by the Next gateway. It is constructed at
 * module initialization, before browser-controlled request data exists.
 */
export const PROCESS_GATEWAY_AUTHORITY = createGatewayAuthority(process.env);
