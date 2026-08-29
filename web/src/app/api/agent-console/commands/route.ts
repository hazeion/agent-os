import { createCommandManifestHandler } from "@/lib/command-manifest-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export const GET = createCommandManifestHandler();
