const OPERATIONS = new Set(["login-start", "login-callback", "login-cancel", "session", "validate", "sign-out", "sign-out-all", "sse-reserve", "sse-check", "sse-release"]);

export class OwnerBridgeError extends Error {
  readonly kind: "unauthenticated" | "unavailable";
  readonly reason: "expired" | "wrong_account" | "unavailable" | "failed";
  constructor(kind: "unauthenticated" | "unavailable" = "unavailable", reason: OwnerBridgeError["reason"] = "failed") { super("owner_authentication_unavailable"); this.kind = kind; this.reason = reason; }
}

/** Fixed owner capabilities only; no browser-selected origin or route. */
export async function ownerCapability(operation: string, body: object): Promise<Record<string, unknown>> {
  if (!OPERATIONS.has(operation)) throw new OwnerBridgeError();
  const token = process.env.MENTAT_BRIDGE_TOKEN ?? "";
  const origin = new URL(process.env.MENTAT_BRIDGE_ORIGIN ?? "http://invalid");
  if (origin.protocol !== "http:" || !["127.0.0.1", "[::1]"].includes(origin.hostname) || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash || !/^[A-Za-z0-9_-]{43,256}$/u.test(token)) throw new OwnerBridgeError();
  try {
    const response = await fetch(new URL(`/bridge/v1/owner/${operation}`, origin), {
      method: "POST", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(operation === "login-callback" ? 15000 : 5000),
      headers: { "Content-Type": "application/json", "X-Mentat-Bridge-Token": token }, body: JSON.stringify(body),
    });
    if (!response.body || !response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) throw new OwnerBridgeError();
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = []; let length = 0;
    try {
      while (true) {
        const result = await reader.read();
        if (result.done) break;
        length += result.value.length;
        if (length > 8192) { await reader.cancel(); throw new OwnerBridgeError(); }
        chunks.push(result.value);
      }
    } finally { reader.releaseLock(); }
    const raw = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { raw.set(chunk, offset); offset += chunk.length; }
    const value: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    if (response.status !== 200) {
      const record = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
      const reason = response.status === 401 && Object.keys(record).sort().join() === "ok,reason" && record.ok === false && ["expired", "wrong_account"].includes(String(record.reason)) ? record.reason as "expired" | "wrong_account" : response.status === 401 ? "failed" : "unavailable";
      throw new OwnerBridgeError(response.status === 401 ? "unauthenticated" : "unavailable", reason);
    }
    if (!value || typeof value !== "object" || Array.isArray(value) || (value as Record<string, unknown>).ok !== true) throw new OwnerBridgeError();
    return value as Record<string, unknown>;
  } catch (error) { if (error instanceof OwnerBridgeError) throw error; throw new OwnerBridgeError(); }
}

export async function validateOwnerSession(value: { cookie: string; csrf: string | null }): Promise<boolean> {
  try { const result = await ownerCapability("validate", value); return Object.keys(result).join() === "ok"; }
  catch (error) { if (error instanceof OwnerBridgeError && error.kind === "unauthenticated") return false; throw error; }
}
