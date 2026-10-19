import { signOutOwner } from "@/lib/owner-auth-routes";
export const POST = signOutOwner(false);
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
