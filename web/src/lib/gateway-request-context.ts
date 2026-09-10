import {
  PROCESS_GATEWAY_AUTHORITY,
  type GatewayAuthority,
  type GatewayAuthorityRequest,
} from "./gateway-authority.ts";
import type { GatewayRouteRule } from "./gateway-route-manifest.ts";

const FORBIDDEN_HEADERS = Object.freeze({
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Content-Type": "text/plain; charset=utf-8",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
});

/** The only route metadata a validated operation may retain. */
export type GatewayRouteValidationContext = Readonly<{ rule: GatewayRouteRule }>;

/**
 * The adapter is deliberately supplied by each operation.  It is the only
 * code in this boundary that receives the original Request, so body parsing
 * and route-specific input validation cannot begin before admission.
 */
export type GatewayRouteValidator<Value, RouteContext = void> = Readonly<{
  validate(request: Request, context: GatewayRouteValidationContext, routeContext: RouteContext): Promise<Value> | Value;
}>;

/**
 * A handler receives only the approved manifest operation and its fixed,
 * validated input.  Gateway headers, gateway mode, and bridge routing details
 * do not cross this boundary.
 */
export type GatewayRouteContext<Value> = GatewayRouteValidationContext & Readonly<{ value: Value }>;
export type GatewayRouteHandler<Value> = (context: GatewayRouteContext<Value>) => Promise<Response> | Response;

type GatewayRouteWrapperOptions<Value, RouteContext> = Readonly<{
  authority?: Pick<GatewayAuthority, "authorize">;
  forbidden?: () => Response;
  handler: GatewayRouteHandler<Value>;
  validator: GatewayRouteValidator<Value, RouteContext>;
}>;

type GatewayRouteFunction<RouteContext> = [RouteContext] extends [void]
  ? (request: Request, routeContext?: unknown) => Promise<Response>
  : (request: Request, routeContext: RouteContext) => Promise<Response>;

function requestAuthorityInput(request: Request): GatewayAuthorityRequest {
  const url = new URL(request.url);
  return {
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    pathname: url.pathname,
    secFetchSite: request.headers.get("sec-fetch-site"),
  };
}

function fixedForbidden(): Response {
  return new Response("Forbidden\n", { headers: FORBIDDEN_HEADERS, status: 403 });
}

/**
 * Admit one exact manifest operation before its validator touches the request.
 * Route-null success is intentionally not a handler fallback: only the Next
 * proxy owns the local static/framework fallback for unmatched paths.
 */
export function withGatewayRoute<Value, RouteContext = void>(
  rule: GatewayRouteRule,
  { authority = PROCESS_GATEWAY_AUTHORITY, forbidden = fixedForbidden, handler, validator }: GatewayRouteWrapperOptions<Value, RouteContext>,
): GatewayRouteFunction<RouteContext> {
  const gatewayRoute = async function gatewayRoute(request: Request, routeContext?: RouteContext): Promise<Response> {
    const decision = authority.authorize(requestAuthorityInput(request));
    if (!decision.allowed || decision.route !== rule) return forbidden();

    const validationContext: GatewayRouteValidationContext = Object.freeze({ rule });
    const value = await validator.validate(request, validationContext, routeContext as RouteContext);
    return handler(Object.freeze({ rule, value }));
  };
  return gatewayRoute as GatewayRouteFunction<RouteContext>;
}
