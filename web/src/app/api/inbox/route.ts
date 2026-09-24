import { createOwnerInboxHandler } from "@/lib/owner-inbox-route";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = createOwnerInboxHandler("page");
