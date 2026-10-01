import { signOutOwner } from "@/lib/owner-auth-routes";
export const POST = signOutOwner(true);
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
