import { startGoogleLogin } from "@/lib/owner-auth-routes";
export async function POST(request: Request) { return startGoogleLogin(request); }
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
