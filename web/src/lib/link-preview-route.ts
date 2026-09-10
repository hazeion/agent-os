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
import { createGatewayAuthority, PROCESS_GATEWAY_AUTHORITY, type GatewayAuthority } from "./gateway-authority.ts";
import { GATEWAY_ROUTE_MANIFEST, type GatewayRouteRule } from "./gateway-route-manifest.ts";
import { withGatewayRoute } from "./gateway-request-context.ts";

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
function route(method: GatewayRouteRule["method"], path: GatewayRouteRule["path"]): GatewayRouteRule {
  const found = GATEWAY_ROUTE_MANIFEST.find((candidate) => candidate.method === method && candidate.path === path);
  if (!found) throw new Error(`missing gateway manifest rule for ${method} ${path}`);
  return found;
}
const MESSAGE_PATH = "/api/conversations/[conversationId]/messages/[messageId]/link-previews" as const;
const MESSAGE_GET_RULE = route("GET", MESSAGE_PATH);
const MESSAGE_POST_RULE = route("POST", MESSAGE_PATH);
const PREFERENCE_PATH = "/api/link-previews/preference" as const;
const PREFERENCE_GET_RULE = route("GET", PREFERENCE_PATH);
const PREFERENCE_POST_RULE = route("POST", PREFERENCE_PATH);
const CACHE_CLEAR_RULE = route("POST", "/api/link-previews/cache/clear");
const IMAGE_RULE = route("GET", "/api/link-previews/images/[imageId]");
function authorityFor(gatewayPort: string | undefined): Pick<GatewayAuthority, "authorize"> {
  return gatewayPort === process.env.PORT ? PROCESS_GATEWAY_AUTHORITY : createGatewayAuthority({ PORT: gatewayPort });
}
function exactRevision(url: URL): number | null {
  if ([...url.searchParams.keys()].join(",") !== "revision") return null;
  const values = url.searchParams.getAll("revision");
  return values.length === 1 && /^[1-9][0-9]{0,9}$/u.test(values[0]) ? Number(values[0]) : null;
}

type Read = (conversationId: string, messageId: string, revision: number) => Promise<PublicLinkPreviewPayload>;
type Mutate = (conversationId: string, messageId: string, revision: number, action: "enqueue" | "retry") => Promise<PublicLinkPreviewPayload>;
type MessageContext = { params: Promise<{ conversationId: string; messageId: string }> };
type MessageReadValue = { conversationId: string; messageId: string; revision: number } | null;
type MessageMutationValue = { conversationId: string; messageId: string; body: { action: "enqueue" | "retry"; messageRevision: number } } | null;

export function createLinkPreviewMessageHandlers({ gatewayPort = process.env.PORT, read = readBridgeLinkPreviews, mutate = mutateBridgeLinkPreviews }: Readonly<{ gatewayPort?: string; read?: Read; mutate?: Mutate }> = {}) {
  return {
    GET: withGatewayRoute<MessageReadValue, MessageContext>(MESSAGE_GET_RULE, {
      authority: authorityFor(gatewayPort),
      handler: async ({ value }) => {
        if (!value) return fixed("invalid", 400);
        try { return Response.json(await read(value.conversationId, value.messageId, value.revision), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
      },
      validator: { async validate(request, _context, context) {
        const revision = exactRevision(new URL(request.url));
        return revision === null ? null : { ...(await context.params), revision };
      } },
    }),
    POST: withGatewayRoute<MessageMutationValue, MessageContext>(MESSAGE_POST_RULE, {
      authority: authorityFor(gatewayPort),
      handler: async ({ value }) => {
        if (!value) return fixed("invalid", 400);
        try { return Response.json(await mutate(value.conversationId, value.messageId, value.body.messageRevision, value.body.action), { headers: HEADERS, status: 202 }); } catch (error) { return failure(error); }
      },
      validator: { async validate(request, _context, context) {
        if (new URL(request.url).search) return null;
        const body = await readLinkPreviewMutationBody(request);
        return body ? { ...(await context.params), body } : null;
      } },
    }),
  };
}

type ReadPreference = () => Promise<PublicLinkPreviewPreference>;
type UpdatePreference = (enabled: boolean, revision: number) => Promise<PublicLinkPreviewPreference>;

export function createLinkPreviewPreferenceHandlers({ gatewayPort = process.env.PORT, read = readBridgeLinkPreviewPreference, update = updateBridgeLinkPreviewPreference }: Readonly<{ gatewayPort?: string; read?: ReadPreference; update?: UpdatePreference }> = {}) {
  return {
    GET: withGatewayRoute<boolean>(PREFERENCE_GET_RULE, {
      authority: authorityFor(gatewayPort),
      handler: async ({ value: hasQuery }) => {
        if (hasQuery) return fixed("invalid", 400);
        try { return Response.json(await read(), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
      },
      validator: { validate(request) { return Boolean(new URL(request.url).search); } },
    }),
    POST: withGatewayRoute<{ enabled: boolean; expectedRevision: number } | null>(PREFERENCE_POST_RULE, {
      authority: authorityFor(gatewayPort),
      handler: async ({ value: body }) => {
        if (!body) return fixed("invalid", 400);
        try { return Response.json(await update(body.enabled, body.expectedRevision), { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
      },
      validator: { async validate(request) { return new URL(request.url).search ? null : readLinkPreviewPreferenceBody(request); } },
    }),
  };
}

export function createLinkPreviewCacheClearHandler({ gatewayPort = process.env.PORT, clear = clearBridgeLinkPreviewCache }: Readonly<{ gatewayPort?: string; clear?: () => Promise<void> }> = {}) {
  return withGatewayRoute<boolean>(CACHE_CLEAR_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value: valid }) => {
      if (!valid) return fixed("invalid", 400);
      try { await clear(); return Response.json({ schema_version: 1, cleared: true, status: "ready" }, { headers: HEADERS, status: 200 }); } catch (error) { return failure(error); }
    },
    validator: { async validate(request) { return !new URL(request.url).search && await hasExactEmptyJsonBody(request); } },
  });
}

export function createLinkPreviewImageHandler({ gatewayPort = process.env.PORT, read = readBridgeLinkPreviewImage }: Readonly<{ gatewayPort?: string; read?: (imageId: string) => Promise<{ body: Uint8Array; maxAge: number }> }> = {}) {
  return withGatewayRoute<string | null, { params: Promise<{ imageId: string }> }>(IMAGE_RULE, {
    authority: authorityFor(gatewayPort),
    handler: async ({ value: imageId }) => {
      if (!imageId) return new Response("Not found\n", { headers: HEADERS, status: 404 });
      try {
      const image = await read(imageId);
      return new Response(image.body as BodyInit, { headers: {
        "Cache-Control": `private, max-age=${image.maxAge}, no-transform`, "Content-Length": String(image.body.byteLength),
        "Content-Security-Policy": "default-src 'none'; sandbox", "Content-Type": "image/webp", "Cross-Origin-Resource-Policy": "same-origin",
        "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
      }, status: 200 });
      } catch (error) { const response = failure(error); return response.status === 404 ? new Response("Not found\n", { headers: HEADERS, status: 404 }) : response; }
    },
    validator: { async validate(request, _context, context) { return new URL(request.url).search ? null : (await context.params).imageId; } },
  });
}
