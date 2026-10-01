import { completeGoogleLogin } from "@/lib/owner-auth-routes";
export async function GET(request: Request) { return completeGoogleLogin(request); }
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
