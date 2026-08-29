import {
  BridgeLinkPreviewError,
  clearBridgeLinkPreviewCache,
  mutateBridgeLinkPreviews,
  readBridgeLinkPreviewImage,
  readBridgeLinkPreviewPreference,
  readBridgeLinkPreviews,
  updateBridgeLinkPreviewPreference,
  type PublicLinkPreviewPayload,
  type PublicLinkPreviewPreference,
} from "./bridge-link-previews.ts";
import { hasExactEmptyJsonBody, readLinkPreviewMutationBody, readLinkPreviewPreferenceBody } from "./exact-json-body.ts";
import { evaluateRequestBoundary, parseGatewayPort } from "./request-boundary.ts";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function fixed(status: string, code: number) { return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code }); }
function failure(error: unknown) {
  if (!(error instanceof BridgeLinkPreviewError)) return fixed("error", 502);
  const map: Record<string, [string, number]> = {
    bridge_unavailable: ["unavailable", 503], link_preview_capacity_unavailable: ["capacity_unavailable", 429],
    link_preview_conflict: ["conflict", 409], link_preview_invalid: ["invalid", 400], link_preview_not_found: ["not_found", 404],
  };
  const result = map[error.code]; return result ? fixed(result[0], result[1]) : fixed("error", 502);
}
function allowed(request: Request, gatewayPort: string | undefined) {
  return evaluateRequestBoundary({ expectedPort: parseGatewayPort(gatewayPort), host: request.headers.get("host"), method: request.method, origin: request.headers.get("origin"), secFetchSite: request.headers.get("sec-fetch-site") }).allowed;
}
function exactRevision(url: URL): number | null {
  if ([...url.searchParams.keys()].join(",") !== "revision") return null;
  const values = url.searchParams.getAll("revision");
  return values.length === 1 && /^[1-9][0-9]{0,9}$/u.test(values[0]) ? Number(values[0]) : null;
}

type Read = (conversationId: string, messageId: string, revision: number) => Promise<PublicLinkPreviewPayload>;
type Mutate = (conversationId: string, messageId: string, revision: number, action: "enqueue" | "retry") => Promise<PublicLinkPreviewPayload>;

export function createLinkPreviewMessageHandlers({ gatewayPort = process.env.PORT, read = readBridgeLinkPreviews, mutate = mutateBridgeLinkPreviews }: Readonly<{ gatewayPort?: string; read?: Read; mutate?: Mutate }> = {}) {
  return {
    GET: async (request: Request, context: { params: Promise<{ conversationId: string; messageId: string }> }) => {
      if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
      const revision = exactRevision(new URL(request.url)); if (revision === null) return fixed("invalid", 400);
      const { conversationId, messageId } = await context.params;
      try { return Response.json(await read(conversationId, messageId, revision), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    POST: async (request: Request, context: { params: Promise<{ conversationId: string; messageId: string }> }) => {
      if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
      if (new URL(request.url).search) return fixed("invalid", 400);
      const body = await readLinkPreviewMutationBody(request); if (!body) return fixed("invalid", 400);
      const { conversationId, messageId } = await context.params;
      try { return Response.json(await mutate(conversationId, messageId, body.messageRevision, body.action), { headers: HEADERS, status: 202 }); } catch (error) { return failure(error); }
    },
  };
}

type ReadPreference = () => Promise<PublicLinkPreviewPreference>;
type UpdatePreference = (enabled: boolean, revision: number) => Promise<PublicLinkPreviewPreference>;

export function createLinkPreviewPreferenceHandlers({ gatewayPort = process.env.PORT, read = readBridgeLinkPreviewPreference, update = updateBridgeLinkPreviewPreference }: Readonly<{ gatewayPort?: string; read?: ReadPreference; update?: UpdatePreference }> = {}) {
  return {
    GET: async (request: Request) => {
      if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
      if (new URL(request.url).search) return fixed("invalid", 400);
      try { return Response.json(await read(), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    POST: async (request: Request) => {
      if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
      if (new URL(request.url).search) return fixed("invalid", 400);
      const body = await readLinkPreviewPreferenceBody(request); if (!body) return fixed("invalid", 400);
      try { return Response.json(await update(body.enabled, body.expectedRevision), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
  };
}

export function createLinkPreviewCacheClearHandler({ gatewayPort = process.env.PORT, clear = clearBridgeLinkPreviewCache }: Readonly<{ gatewayPort?: string; clear?: () => Promise<void> }> = {}) {
  return async (request: Request) => {
    if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
    if (new URL(request.url).search || !await hasExactEmptyJsonBody(request)) return fixed("invalid", 400);
    try { await clear(); return Response.json({ schema_version: 1, cleared: true, status: "ready" }, { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
  };
}

export function createLinkPreviewImageHandler({ gatewayPort = process.env.PORT, read = readBridgeLinkPreviewImage }: Readonly<{ gatewayPort?: string; read?: (imageId: string) => Promise<{ body: Uint8Array; maxAge: number }> }> = {}) {
  return async (request: Request, context: { params: Promise<{ imageId: string }> }) => {
    if (!allowed(request, gatewayPort)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
    if (new URL(request.url).search) return new Response("Not found\n", { headers: HEADERS, status: 404 });
    const { imageId } = await context.params;
    try {
      const image = await read(imageId);
      return new Response(image.body as BodyInit, { headers: {
        "Cache-Control": `private, max-age=${image.maxAge}, no-transform`, "Content-Length": String(image.body.byteLength),
        "Content-Security-Policy": "default-src 'none'; sandbox", "Content-Type": "image/webp", "Cross-Origin-Resource-Policy": "same-origin",
        "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
      }, status: 200 });
    } catch (error) { const response = failure(error); return response.status === 404 ? new Response("Not found\n", { headers: HEADERS, status: 404 }) : response; }
  };
}
