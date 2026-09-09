/**
 * The checked-in gateway inventory is deliberately declarative. It names each
 * current API operation and the finite static surface that the shipped
 * dashboard needs. Consuming it must not change current local-only behaviour
 * until the corresponding route migration is complete.
 */
export const GATEWAY_HTTP_METHODS = ["GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "DELETE"] as const;
export type GatewayHttpMethod = typeof GATEWAY_HTTP_METHODS[number];
export type GatewayRouteExposure = "local_only" | "anonymous_auth" | "owner_session" | "owner_reauth" | "static";
export type GatewayCsrfRule = "not_required" | "session_bound";
export type GatewayIdempotencyRule = "not_applicable" | "route_owned";
export type GatewayBudgetClass = "gateway_read" | "gateway_mutation" | "gateway_stream";
export type GatewaySafeProjection = "route_owned" | "static";
export type GatewayAuditEvent = "gateway_api_read" | "gateway_api_mutation" | "gateway_static_read";
export type GatewayBridgeCapability = `bridge:${string}`;
export type GatewayRouteSource = `web/${string}` | "framework:next";

export type GatewayRouteRule = Readonly<{
  audit: GatewayAuditEvent;
  bridgeCapability: GatewayBridgeCapability | null;
  budget: GatewayBudgetClass;
  csrf: GatewayCsrfRule;
  exposure: GatewayRouteExposure;
  idempotency: GatewayIdempotencyRule;
  method: GatewayHttpMethod;
  path: `/${string}`;
  projection: GatewaySafeProjection;
  source: GatewayRouteSource;
  validator: `route:${string}` | `static:${string}`;
}>;

const SAFE_METHODS = new Set<GatewayHttpMethod>(["GET", "HEAD", "OPTIONS"]);
const SUPERVISOR_PATHS = new Set(["/api/bridge/health", "/api/gateway/health"]);

function routeCapability(path: string, method: GatewayHttpMethod): GatewayBridgeCapability {
  return `bridge:${path.slice("/api/".length).replaceAll("/", ".")}.${method.toLowerCase()}`;
}

function routeValidator(source: string, method: GatewayHttpMethod): `route:${string}` {
  return `route:${source.slice("web/src/app/api/".length, -"/route.ts".length)}#${method}`;
}

function rule(method: GatewayHttpMethod, path: `/api${string}`, source: `web/src/app/api/${string}/route.ts`): GatewayRouteRule {
  const safe = SAFE_METHODS.has(method);
  const supervisor = SUPERVISOR_PATHS.has(path);
  return Object.freeze({
    audit: safe ? "gateway_api_read" : "gateway_api_mutation",
    bridgeCapability: supervisor ? null : routeCapability(path, method),
    budget: path.endsWith("/events") ? "gateway_stream" : safe ? "gateway_read" : "gateway_mutation",
    csrf: safe ? "not_required" : "session_bound",
    // These target exposure classes are declarative only.  The current process
    // remains local-only until handlers are migrated through the authority.
    exposure: supervisor ? "local_only" : "owner_session",
    idempotency: safe ? "not_applicable" : "route_owned",
    method,
    path,
    projection: "route_owned",
    source,
    validator: routeValidator(source, method),
  });
}

function staticRule(path: `/${string}`, source: GatewayRouteSource): GatewayRouteRule[] {
  return (["GET", "HEAD"] as const).map((method) => Object.freeze({
    audit: "gateway_static_read" as const,
    bridgeCapability: null,
    budget: "gateway_read" as const,
    csrf: "not_required" as const,
    exposure: "static" as const,
    idempotency: "not_applicable" as const,
    method,
    path,
    projection: "static" as const,
    source,
    validator: `static:${path}` as const,
  }));
}

/** Exactly one frozen row per API operation and per static method/surface pair. */
export const GATEWAY_ROUTE_MANIFEST: readonly GatewayRouteRule[] = Object.freeze([
  rule("GET", "/api/agent-activity", "web/src/app/api/agent-activity/route.ts"),
  rule("GET", "/api/agent-console/commands", "web/src/app/api/agent-console/commands/route.ts"),
  rule("GET", "/api/agent-console/planning-calendar", "web/src/app/api/agent-console/planning-calendar/route.ts"),
  rule("GET", "/api/agent-console/planning-dependency-map", "web/src/app/api/agent-console/planning-dependency-map/route.ts"),
  rule("GET", "/api/agent-console/planning-dependency-picker", "web/src/app/api/agent-console/planning-dependency-picker/route.ts"),
  rule("GET", "/api/agent-console/planning-note-picker", "web/src/app/api/agent-console/planning-note-picker/route.ts"),
  rule("GET", "/api/agent-console/planning-overview", "web/src/app/api/agent-console/planning-overview/route.ts"),
  rule("GET", "/api/agent-console/planning-search", "web/src/app/api/agent-console/planning-search/route.ts"),
  rule("GET", "/api/agent-console/planning-task-delegation/options", "web/src/app/api/agent-console/planning-task-delegation/options/route.ts"),
  rule("GET", "/api/agent-console/planning-task-delegation", "web/src/app/api/agent-console/planning-task-delegation/route.ts"),
  rule("GET", "/api/agent-console/planning-task-dependencies", "web/src/app/api/agent-console/planning-task-dependencies/route.ts"),
  rule("GET", "/api/agent-console/planning-task-detail", "web/src/app/api/agent-console/planning-task-detail/route.ts"),
  rule("GET", "/api/agent-console/planning-task-execution", "web/src/app/api/agent-console/planning-task-execution/route.ts"),
  rule("GET", "/api/agent-console/planning-task", "web/src/app/api/agent-console/planning-task/route.ts"),
  rule("GET", "/api/agent-console/planning-tasks", "web/src/app/api/agent-console/planning-tasks/route.ts"),
  rule("POST", "/api/agent-setup/check", "web/src/app/api/agent-setup/check/route.ts"),
  rule("POST", "/api/agent-setup/confirm", "web/src/app/api/agent-setup/confirm/route.ts"),
  rule("POST", "/api/agent-setup/preview", "web/src/app/api/agent-setup/preview/route.ts"),
  rule("POST", "/api/agents/[agentId]/attachments/enable", "web/src/app/api/agents/[agentId]/attachments/enable/route.ts"),
  rule("GET", "/api/agents/[agentId]/attachments/enable", "web/src/app/api/agents/[agentId]/attachments/enable/route.ts"),
  rule("POST", "/api/agents/[agentId]/configuration/preview", "web/src/app/api/agents/[agentId]/configuration/preview/route.ts"),
  rule("GET", "/api/agents/[agentId]/configuration", "web/src/app/api/agents/[agentId]/configuration/route.ts"),
  rule("POST", "/api/agents/[agentId]/configuration", "web/src/app/api/agents/[agentId]/configuration/route.ts"),
  rule("POST", "/api/agents/[agentId]/task-creation/enable", "web/src/app/api/agents/[agentId]/task-creation/enable/route.ts"),
  rule("GET", "/api/agents/[agentId]/task-creation/enable", "web/src/app/api/agents/[agentId]/task-creation/enable/route.ts"),
  rule("GET", "/api/agents", "web/src/app/api/agents/route.ts"),
  rule("GET", "/api/bridge/health", "web/src/app/api/bridge/health/route.ts"),
  rule("GET", "/api/codex-readiness", "web/src/app/api/codex-readiness/route.ts"),
  rule("GET", "/api/context-packs", "web/src/app/api/context-packs/route.ts"),
  rule("GET", "/api/conversation-history", "web/src/app/api/conversation-history/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/archive", "web/src/app/api/conversations/[conversationId]/archive/route.ts"),
  rule("GET", "/api/conversations/[conversationId]/attachments/[attachmentId]/content", "web/src/app/api/conversations/[conversationId]/attachments/[attachmentId]/content/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/attachments/[attachmentId]/release", "web/src/app/api/conversations/[conversationId]/attachments/[attachmentId]/release/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/attachments", "web/src/app/api/conversations/[conversationId]/attachments/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/context-packs/[packId]", "web/src/app/api/conversations/[conversationId]/context-packs/[packId]/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/context-packs/release", "web/src/app/api/conversations/[conversationId]/context-packs/release/route.ts"),
  rule("GET", "/api/conversations/[conversationId]/media", "web/src/app/api/conversations/[conversationId]/media/route.ts"),
  rule("GET", "/api/conversations/[conversationId]/messages/[messageId]/link-previews", "web/src/app/api/conversations/[conversationId]/messages/[messageId]/link-previews/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/messages/[messageId]/link-previews", "web/src/app/api/conversations/[conversationId]/messages/[messageId]/link-previews/route.ts"),
  rule("GET", "/api/conversations/[conversationId]/planning-context", "web/src/app/api/conversations/[conversationId]/planning-context/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/planning-context", "web/src/app/api/conversations/[conversationId]/planning-context/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/rename", "web/src/app/api/conversations/[conversationId]/rename/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/restore", "web/src/app/api/conversations/[conversationId]/restore/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/resume", "web/src/app/api/conversations/[conversationId]/resume/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/retry", "web/src/app/api/conversations/[conversationId]/retry/route.ts"),
  rule("GET", "/api/conversations/[conversationId]", "web/src/app/api/conversations/[conversationId]/route.ts"),
  rule("GET", "/api/conversations/[conversationId]/staged-context", "web/src/app/api/conversations/[conversationId]/staged-context/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/steer", "web/src/app/api/conversations/[conversationId]/steer/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/turns/[turnId]/cancel", "web/src/app/api/conversations/[conversationId]/turns/[turnId]/cancel/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/turns/[turnId]/continue", "web/src/app/api/conversations/[conversationId]/turns/[turnId]/continue/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/turns/[turnId]/edit", "web/src/app/api/conversations/[conversationId]/turns/[turnId]/edit/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/turns", "web/src/app/api/conversations/[conversationId]/turns/route.ts"),
  rule("GET", "/api/conversations/[conversationId]/uploads/[uploadId]", "web/src/app/api/conversations/[conversationId]/uploads/[uploadId]/route.ts"),
  rule("POST", "/api/conversations/[conversationId]/workspace-files", "web/src/app/api/conversations/[conversationId]/workspace-files/route.ts"),
  rule("GET", "/api/conversations", "web/src/app/api/conversations/route.ts"),
  rule("POST", "/api/conversations", "web/src/app/api/conversations/route.ts"),
  rule("GET", "/api/gateway/health", "web/src/app/api/gateway/health/route.ts"),
  rule("POST", "/api/link-previews/cache/clear", "web/src/app/api/link-previews/cache/clear/route.ts"),
  rule("GET", "/api/link-previews/images/[imageId]", "web/src/app/api/link-previews/images/[imageId]/route.ts"),
  rule("GET", "/api/link-previews/preference", "web/src/app/api/link-previews/preference/route.ts"),
  rule("POST", "/api/link-previews/preference", "web/src/app/api/link-previews/preference/route.ts"),
  rule("POST", "/api/planning/[kind]/[id]/[action]", "web/src/app/api/planning/[kind]/[id]/[action]/route.ts"),
  rule("POST", "/api/planning/projects/[targetId]/delete/preview", "web/src/app/api/planning/projects/[targetId]/delete/preview/route.ts"),
  rule("POST", "/api/planning/projects/[targetId]/delete", "web/src/app/api/planning/projects/[targetId]/delete/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/delegation/action/preview", "web/src/app/api/planning/tasks/[taskId]/delegation/action/preview/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/delegation/action", "web/src/app/api/planning/tasks/[taskId]/delegation/action/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/delegation/delegate", "web/src/app/api/planning/tasks/[taskId]/delegation/delegate/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/delegation/preview", "web/src/app/api/planning/tasks/[taskId]/delegation/preview/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/delegation/recover", "web/src/app/api/planning/tasks/[taskId]/delegation/recover/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/delegation/refresh", "web/src/app/api/planning/tasks/[taskId]/delegation/refresh/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/delete/preview", "web/src/app/api/planning/tasks/[taskId]/delete/preview/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/delete", "web/src/app/api/planning/tasks/[taskId]/delete/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/execution/refresh", "web/src/app/api/planning/tasks/[taskId]/execution/refresh/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/execution/review", "web/src/app/api/planning/tasks/[taskId]/execution/review/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/execution/run-once/preview", "web/src/app/api/planning/tasks/[taskId]/execution/run-once/preview/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/execution/run-once", "web/src/app/api/planning/tasks/[taskId]/execution/run-once/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/integrations/calendar/link", "web/src/app/api/planning/tasks/[taskId]/integrations/calendar/link/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/integrations/calendar/unlink", "web/src/app/api/planning/tasks/[taskId]/integrations/calendar/unlink/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/integrations/notes/attach", "web/src/app/api/planning/tasks/[taskId]/integrations/notes/attach/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/integrations/notes/detach", "web/src/app/api/planning/tasks/[taskId]/integrations/notes/detach/route.ts"),
  rule("POST", "/api/planning/tasks/[taskId]/integrations/reminders", "web/src/app/api/planning/tasks/[taskId]/integrations/reminders/route.ts"),
  rule("POST", "/api/projects/[projectId]/tasks", "web/src/app/api/projects/[projectId]/tasks/route.ts"),
  rule("POST", "/api/projects", "web/src/app/api/projects/route.ts"),
  rule("GET", "/api/provider-connections", "web/src/app/api/provider-connections/route.ts"),
  rule("GET", "/api/runs/[runId]/events", "web/src/app/api/runs/[runId]/events/route.ts"),
  rule("POST", "/api/runs/[runId]/message/preview", "web/src/app/api/runs/[runId]/message/preview/route.ts"),
  rule("POST", "/api/runs/[runId]/message", "web/src/app/api/runs/[runId]/message/route.ts"),
  rule("POST", "/api/runs/[runId]/response/preview", "web/src/app/api/runs/[runId]/response/preview/route.ts"),
  rule("POST", "/api/runs/[runId]/response", "web/src/app/api/runs/[runId]/response/route.ts"),
  rule("POST", "/api/runs/[runId]/stop/preview", "web/src/app/api/runs/[runId]/stop/preview/route.ts"),
  rule("POST", "/api/runs/[runId]/stop", "web/src/app/api/runs/[runId]/stop/route.ts"),
  rule("GET", "/api/runs", "web/src/app/api/runs/route.ts"),
  rule("GET", "/api/tasks", "web/src/app/api/tasks/route.ts"),
  rule("GET", "/api/workspace-files", "web/src/app/api/workspace-files/route.ts"),
  ...staticRule("/", "web/src/app/page.tsx"),
  ...staticRule("/agents", "web/src/app/agents/page.tsx"),
  ...staticRule("/tasks", "web/src/app/tasks/page.tsx"),
  ...staticRule("/runs", "web/src/app/runs/page.tsx"),
  ...staticRule("/icon.svg", "web/src/app/icon.svg"),
  ...staticRule("/mentat-mark-emerald.png", "web/public/mentat-mark-emerald.png"),
  ...staticRule("/agent-setup.js", "web/public/agent-setup.js"),
  ...staticRule("/shell-runtime.js", "web/public/shell-runtime.js"),
  ...staticRule("/shell/agents.html", "web/scripts/prepare-standalone.mjs"),
  ...staticRule("/shell/runs.html", "web/scripts/prepare-standalone.mjs"),
  ...staticRule("/_next/static/[...path]", "framework:next"),
]);
