import { createCommandManifestHandler } from "@/lib/command-manifest-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const get = createCommandManifestHandler();
export async function GET(request: Request) { return get(request); }
