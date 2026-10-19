import { readOwnerSession } from "@/lib/owner-auth-routes";
export async function GET(request: Request) { return readOwnerSession(request); }
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
