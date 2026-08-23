export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const RESPONSE_HEADERS = {
  "Cache-Control": "private, no-store",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

/** A fixed readiness check for the public Node gateway only. */
export async function GET() {
  return Response.json(
    { gateway: "mentat-node-gateway", status: "ready" },
    { headers: RESPONSE_HEADERS, status: 200 },
  );
}
