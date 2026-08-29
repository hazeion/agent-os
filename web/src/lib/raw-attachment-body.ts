import { MAXIMUM_ATTACHMENT_BYTES, UPLOAD_CONTENT_TYPES } from "./bridge-conversation-media.ts";

const READ_TIMEOUT_MILLISECONDS = 15_000;

export type RawAttachmentBody = {
  body: Uint8Array;
  contentType: string;
  encodedFilename: string;
};

function canonicalFilename(value: string | null): string | null {
  if (!value || value.length > 1_024 || value.includes(",")) return null;
  let decoded: string;
  try { decoded = decodeURIComponent(value); } catch { return null; }
  if (
    !decoded
    || [...decoded].length > 255
    || decoded.trim() !== decoded
    || decoded === "."
    || decoded === ".."
    || decoded.includes("/")
    || decoded.includes("\\")
    || /[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u.test(decoded)
    || encodeURIComponent(decoded) !== value
  ) return null;
  return value;
}

export async function readRawAttachmentBody(
  request: Request,
  timeoutMilliseconds = READ_TIMEOUT_MILLISECONDS,
): Promise<RawAttachmentBody | null> {
  if (request.headers.has("transfer-encoding") || request.headers.has("content-encoding")) return null;
  const declared = request.headers.get("content-length");
  const contentType = request.headers.get("content-type")?.trim().toLowerCase() ?? "";
  const encodedFilename = canonicalFilename(request.headers.get("x-mentat-filename"));
  if (
    !declared
    || !/^[1-9][0-9]{0,8}$/u.test(declared)
    || Number(declared) > MAXIMUM_ATTACHMENT_BYTES
    || !UPLOAD_CONTENT_TYPES.has(contentType)
    || encodedFilename === null
    || !request.body
    || !Number.isSafeInteger(timeoutMilliseconds)
    || timeoutMilliseconds < 1
  ) return null;

  const expected = Number(declared);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error("body_read_timeout")), timeoutMilliseconds);
  });
  try {
    for (;;) {
      const next = await Promise.race([reader.read(), deadline]);
      if (next.done) break;
      size += next.value.byteLength;
      if (size > expected) {
        void reader.cancel().catch(() => undefined);
        return null;
      }
      chunks.push(next.value);
    }
  } catch {
    void reader.cancel().catch(() => undefined);
    return null;
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    reader.releaseLock();
  }
  if (size !== expected) return null;
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  return { body, contentType, encodedFilename };
}
