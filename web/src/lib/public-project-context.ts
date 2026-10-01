import { ownerFetch } from "../../public/owner-session.js";
import { contextRequest, contextResult, type ContextOperation, type ContextResults } from "./project-context-contract.ts";

export class ProjectContextClientError extends Error { constructor(readonly code: string) { super(code); } }
export function projectContextFileUrl(attachmentId: string, target: { project_id: string } | { context_id: string }): string {
  contextRequest("file", { ...target, attachment_id: attachmentId });
  return "project_id" in target ? `/api/projects/${encodeURIComponent(target.project_id)}/context/files/${attachmentId}` : `/api/project-context/${target.context_id}/files/${attachmentId}`;
}
export async function readOrChangeProjectContext<K extends Exclude<ContextOperation, "file">>(operation: K, input: unknown): Promise<ContextResults[K]> {
  const value = { ...contextRequest(operation, input) };
  const project = `/api/projects/${encodeURIComponent(String(value.project_id))}/context`;
  const version = `/api/project-context/${String(value.context_id)}`;
  const routes = {
    project: ["GET", project, ["project_id"]], publish: ["POST", project, ["project_id"]],
    upload: ["POST", `${project}/files`, ["project_id"]], discard: ["DELETE", `${project}/files/${String(value.attachment_id)}`, ["project_id", "attachment_id"]],
    version: ["GET", version, ["context_id"]], history: ["GET", "/api/project-context/history", []],
    "grant-preview": ["POST", `${version}/grant/preview`, ["context_id"]], "grant-confirm": ["POST", `${version}/grant`, ["context_id"]],
    revoke: ["POST", `${project}/revoke`, ["project_id"]], "prune-preview": ["POST", `${version}/prune/preview`, ["context_id"]], "prune-confirm": ["POST", `${version}/prune`, ["context_id"]],
  } as const;
  const [method, url, fields] = routes[operation];
  for (const field of fields) delete value[field];
  const response = await ownerFetch(url, { method, cache: "no-store", credentials: "same-origin", redirect: "error", signal: AbortSignal.timeout(35_000), headers: { Accept: "application/json", ...(method === "GET" ? {} : { "Content-Type": "application/json" }) }, ...(method === "GET" ? {} : { body: JSON.stringify(value) }) });
  if (!response.body) throw new ProjectContextClientError("unavailable");
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try { for (;;) { const next = await reader.read(); if (next.done) break; size += next.value.byteLength; if (size > 512 * 1024) { await reader.cancel(); throw new ProjectContextClientError("unavailable"); } chunks.push(next.value); } } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  let payload: unknown;
  try { payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { throw new ProjectContextClientError("unavailable"); }
  if (response.status !== 200) {
    const status = payload && typeof payload === "object" && "status" in payload ? String(payload.status) : "unavailable";
    throw new ProjectContextClientError(["stale", "project_changed", "staging_changed", "revision_conflict", "capacity", "file_unavailable", "granted_version", "current_version"].includes(status) ? status : "unavailable");
  }
  return contextResult(operation, payload, contextRequest(operation, input));
}

export async function projectFileBase64(file: File): Promise<string> {
  if (file.size > 10 * 1024 * 1024) throw new ProjectContextClientError("capacity");
  const bytes = new Uint8Array(await file.arrayBuffer()); let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(binary);
}
