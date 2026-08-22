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

async function readBoundedJson(request: Request, maximumBytes: number): Promise<unknown | null> {
  if (request.headers.get("content-type")?.toLowerCase() !== "application/json" || !request.body) return null;
  const reader = request.body.getReader(); const parts: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > maximumBytes) { await reader.cancel(); return null; } parts.push(next.value); } } catch { return null; }
  const value = new Uint8Array(size); let offset = 0;
  for (const part of parts) { value.set(part, offset); offset += part.byteLength; }
  try { return JSON.parse(new TextDecoder().decode(value)); } catch { return null; }
}

const RUN_MESSAGE_TEXT_LIMIT = 6_000;
const withinRunMessageTextLimit = (text: string) => Array.from(text).length <= RUN_MESSAGE_TEXT_LIMIT;

export async function readMessagePreview(request: Request): Promise<string | null> {
  const body = await readBoundedJson(request, 24_576);
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).join(",") !== "text") return null;
  const text = (body as Record<string, unknown>).text;
  return typeof text === "string" && text.trim() && withinRunMessageTextLimit(text) && !text.includes("\0") ? text : null;
}

export async function readMessageConfirmation(request: Request): Promise<{ text: string; confirmationId: string } | null> {
  const body = await readBoundedJson(request, 24_576);
  if (!body || typeof body !== "object" || Array.isArray(body) || Object.keys(body).sort().join(",") !== "confirmation_id,text") return null;
  const text = (body as Record<string, unknown>).text;
  const confirmationId = (body as Record<string, unknown>).confirmation_id;
  return typeof text === "string" && text.trim() && withinRunMessageTextLimit(text) && !text.includes("\0") && typeof confirmationId === "string" && /^[0-9a-f]{64}$/u.test(confirmationId) ? { text, confirmationId } : null;
}
