import {
  BridgeCommandManifestError,
  fetchBridgeCommandManifest,
} from "./bridge-command-manifest.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";
import type { PublicCommandManifest } from "./public-command-manifest.ts";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixed(status: string, code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

export function createCommandManifestHandler({
  fetchManifest = fetchBridgeCommandManifest,
  gatewayPort = process.env.PORT,
}: Readonly<{
  fetchManifest?: () => Promise<PublicCommandManifest>;
  gatewayPort?: string;
}> = {}) {
  return async function getCommandManifest(request: Request) {
    const decision = evaluateRequestBoundary({
      expectedPort: parseGatewayPort(gatewayPort),
      host: request.headers.get("host"),
      method: request.method,
      origin: request.headers.get("origin"),
      secFetchSite: request.headers.get("sec-fetch-site"),
    });
    if (!decision.allowed) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
    if (new URL(request.url).search) return fixed("invalid", 400);
    try {
      return Response.json(await fetchManifest(), { headers: HEADERS });
    } catch (error) {
      if (error instanceof BridgeCommandManifestError && error.code === "bridge_unavailable") {
        return fixed("unavailable", 503);
      }
      return fixed("error", 502);
    }
  };
}
