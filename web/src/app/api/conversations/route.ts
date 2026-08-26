import {
  BridgeConversationsError,
  createBridgeConversation,
  fetchBridgeConversations,
} from "@/lib/bridge-conversations";
import { evaluateRequestBoundary, parseGatewayPort } from "@/lib/request-boundary";
import { readConversationCreateBody } from "@/lib/exact-json-body";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

function state(status: "error" | "not_found" | "unavailable" | "unsupported", code: number) {
  return Response.json({ schema_version: 1, status }, { headers: HEADERS, status: code });
}

function boundary(request: Request) {
  return evaluateRequestBoundary({
    expectedPort: parseGatewayPort(process.env.PORT),
    host: request.headers.get("host"),
    method: request.method,
    origin: request.headers.get("origin"),
    secFetchSite: request.headers.get("sec-fetch-site"),
  }).allowed;
}

function errorResponse(error: unknown) {
  if (error instanceof BridgeConversationsError && error.code === "bridge_unsupported") return state("unsupported", 501);
  if (error instanceof BridgeConversationsError && error.code === "bridge_unavailable") return state("unavailable", 503);
  return state("error", 502);
}

export async function GET(request: Request) {
  if (!boundary(request)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
  const entries = [...new URL(request.url).searchParams.entries()];
  if (entries.length > 1 || entries.length === 1 && (entries[0][0] !== "cursor" || !/^[A-Za-z0-9_-]{1,256}$/u.test(entries[0][1]))) return state("error", 400);
  try {
    return Response.json(await fetchBridgeConversations(undefined, undefined, entries[0]?.[1] ?? null), { headers: HEADERS });
  } catch (error) {
    return errorResponse(error);
  }
}

export async function POST(request: Request) {
  if (!boundary(request)) return new Response("Forbidden\n", { headers: HEADERS, status: 403 });
  const body = await readConversationCreateBody(request);
  if (!body) return state("error", 400);
  try {
    return Response.json(await createBridgeConversation(body.agentId), {
      headers: HEADERS,
      status: 201,
    });
  } catch (error) {
    if (error instanceof BridgeConversationsError && error.code === "agent_id_invalid") return state("error", 400);
    if (error instanceof BridgeConversationsError && error.code === "conversation_not_found") return state("not_found", 404);
    return errorResponse(error);
  }
}
