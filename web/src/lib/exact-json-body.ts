/** Read at most two bytes and accept only the fixed preview body. */
export async function hasExactEmptyJsonBody(request: Request): Promise<boolean> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return false;
  const reader = request.body.getReader(); const parts: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > 2) { await reader.cancel(); return false; }
      parts.push(next.value);
    }
  } catch { return false; }
  const value = new Uint8Array(size); let offset = 0;
  for (const part of parts) { value.set(part, offset); offset += part.byteLength; }
  return new TextDecoder().decode(value) === "{}";
}

/** Return one fixed confirmation value without buffering an arbitrary body. */
export async function readConfirmationId(request: Request): Promise<string | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const reader = request.body.getReader(); const parts: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > 128) { await reader.cancel(); return null; }
      parts.push(next.value);
    }
  } catch { return null; }
  const value = new Uint8Array(size); let offset = 0;
  for (const part of parts) { value.set(part, offset); offset += part.byteLength; }
  let body: unknown;
  try { body = JSON.parse(new TextDecoder().decode(value)); } catch { return null; }
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).join(",") !== "confirmation_id") return null;
  const confirmationId = (body as Record<string, unknown>).confirmation_id;
  return typeof confirmationId === "string" && /^[0-9a-f]{64}$/u.test(confirmationId) ? confirmationId : null;
}
