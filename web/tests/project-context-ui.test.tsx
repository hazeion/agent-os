import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
import { useState } from "react";
import type { ProjectContextDraft } from "../src/app/tasks/project-context-editor.tsx";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://127.0.0.1:8890/tasks", pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { render, screen, fireEvent, waitFor, cleanup, within } = await import("@testing-library/react");
const { ProjectContextEditor, RetiredProjectContextHistory } = await import("../src/app/tasks/project-context-editor.tsx");
const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });
const projectId = "project_garage", contextId = `project_context_${"a".repeat(32)}`, attachmentId = `attachment_${"b".repeat(32)}`;
const file = { id: attachmentId, name: "floorplan.md", mime_type: "text/markdown", kind: "text", byte_size: 4, state: "attached", created_at: "2026-09-22T00:00:00Z", expires_at: null, available: true };
const version = { id: contextId, revision: 1, created_at: 1790035200, project_id: projectId, brief: "Keep bicycle access clear", retired: false, current: true, files: [file], prune_blocked: "current_version" };
function fixture() {
  const state = { current: structuredClone(version), grants: [] as Array<{ agent_id: string; context_id: string; revision: number; state: string; reason: string | null }>, calls: [] as Array<{ path: string; body: Record<string, unknown> | null }>, failPublish: false };
  globalThis.fetch = async (input, init) => {
    const path = String(input); const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null; state.calls.push({ path, body });
    if (path.endsWith("/grant/preview")) return Response.json({ project_id: projectId, context_id: contextId, context_revision: 1, brief: version.brief, files: [file], agent_id: "agent_research", agent_name: "Research Agent", grant_revision: 0, confirmation_id: "f".repeat(64) });
    if (path.endsWith("/grant")) { state.grants = [{ agent_id: "agent_research", context_id: contextId, revision: 1, state: "active", reason: null }]; return Response.json({ project_id: projectId, context_id: contextId, agent_id: "agent_research", revision: 1, state: "active" }); }
    if (path.endsWith("/revoke")) { state.grants = [{ ...state.grants[0], revision: 2, state: "revoked", reason: "owner" }]; return Response.json({ project_id: projectId, context_id: contextId, agent_id: "agent_research", revision: 2, state: "revoked" }); }
    if (path.endsWith("/context") && init?.method === "POST") {
      if (state.failPublish) return Response.json({ schema_version: 1, status: "stale" }, { status: 409 });
      state.current = { ...state.current, id: `project_context_${"c".repeat(32)}`, revision: 2, brief: String(body?.brief) };
      return Response.json({ context_id: state.current.id, revision: 2 });
    }
    if (path === `/api/projects/${projectId}/context`) return Response.json({ project: { id: projectId, name: "Garage", revision: 1, status: "active" }, current: state.current, versions: [{ id: state.current.id, revision: state.current.revision, created_at: version.created_at }], staged: [], grants: state.grants });
    throw new Error(`Unexpected test request ${path}`);
  };
  return state;
}
async function openEditor() { render(<ProjectContextEditor projectId={projectId} agents={[{ id: "agent_research", name: "Research Agent" }]} />); fireEvent.click(screen.getByRole("button", { name: "Open context" })); await screen.findByLabelText("Goals and constraints"); }
function DraftWorkspace() {
  const [selected, setSelected] = useState(projectId); const [drafts, setDrafts] = useState<Record<string, ProjectContextDraft | null>>({});
  return <><button onClick={() => setSelected(selected === projectId ? "project_other" : projectId)}>Switch Project</button><ProjectContextEditor key={selected} projectId={selected} agents={[]} draft={drafts[selected]} onDraftChange={(update) => setDrafts((current) => ({ ...current, [selected]: update(current[selected] ?? null) }))} /></>;
}

test("owner reviews an exact saved version before granting access and can revoke it", async () => {
  const state = fixture(); await openEditor();
  fireEvent.change(screen.getByLabelText("Agent"), { target: { value: "agent_research" } });
  fireEvent.click(screen.getByRole("button", { name: "Review Agent access" }));
  const preview = await screen.findByLabelText("Agent access preview");
  assert.match(preview.textContent ?? "", /Keep bicycle access clear/u);
  assert.equal(within(preview).getByRole("link", { name: "floorplan.md" }).getAttribute("href"), `/api/project-context/${contextId}/files/${attachmentId}`);
  assert.equal(state.grants.length, 0);
  fireEvent.click(within(preview).getByRole("button", { name: "Approve access" }));
  await screen.findByText("Agent access approved for the reviewed version.");
  fireEvent.click(screen.getByRole("button", { name: "Revoke access" }));
  await screen.findByText("Agent access revoked.");
  const revoke = state.calls.find((call) => call.path.endsWith("/revoke"));
  assert.deepEqual(revoke?.body, { context_id: contextId, agent_id: "agent_research", expected_revision: 1 });
  assert.equal(state.calls.some((call) => /run|dispatch|turn/u.test(call.path)), false);
});

test("failed publication and refresh preserve the owner's draft and selected files", async () => {
  const state = fixture(); state.failPublish = true; await openEditor();
  fireEvent.change(screen.getByLabelText("Goals and constraints"), { target: { value: "Reserve space for a workbench" } });
  fireEvent.click(screen.getByRole("button", { name: "Publish context version" }));
  await screen.findByText(/This Project changed/u);
  assert.equal((screen.getByLabelText("Goals and constraints") as HTMLTextAreaElement).value, "Reserve space for a workbench");
  state.current.brief = "Changed from another device";
  fireEvent.click(screen.getByRole("button", { name: "Refresh context" }));
  await waitFor(() => assert.equal((screen.getByRole("button", { name: "Refresh context" }) as HTMLButtonElement).disabled, false));
  assert.equal((screen.getByLabelText("Goals and constraints") as HTMLTextAreaElement).value, "Reserve space for a workbench");
  const publish = state.calls.find((call) => call.path.endsWith("/context") && call.body);
  assert.deepEqual(publish?.body?.attachment_ids, [attachmentId]); assert.deepEqual(publish?.body?.expected_staged_ids, []);
});

test("publishing does not grant Agents the new version", async () => {
  const state = fixture(); await openEditor();
  fireEvent.change(screen.getByLabelText("Goals and constraints"), { target: { value: "Add a storage wall" } });
  fireEvent.click(screen.getByRole("button", { name: "Publish context version" }));
  await screen.findByText(/Saved a new context version/u);
  assert.equal(state.grants.length, 0);
  assert.equal(state.calls.some((call) => call.path.includes("/grant")), false);
});

test("retired history stays separate and requires explicit removal confirmation", async () => {
  let removed = false; const calls: string[] = [];
  globalThis.fetch = async (input) => {
    const path = String(input); calls.push(path);
    if (path.endsWith("/history")) return Response.json({ versions: removed ? [] : [{ id: contextId, revision: 1, created_at: version.created_at, summary: "Old garage brief" }] });
    if (path.endsWith("/prune/preview")) return Response.json({ context_id: contextId, revision: 1, file_count: 1, confirmation_id: "f".repeat(64) });
    if (path.endsWith("/prune")) { removed = true; return Response.json({ pruned: true }); }
    return Response.json({ ...version, retired: true, current: false, prune_blocked: null });
  };
  render(<RetiredProjectContextHistory />);
  fireEvent.click(screen.getByRole("button", { name: "Retained Project history" }));
  fireEvent.click(await screen.findByRole("button", { name: "View saved version" }));
  fireEvent.click(await screen.findByRole("button", { name: "Review removal" }));
  const confirm = await screen.findByRole("button", { name: "Confirm removal" }); assert.equal(removed, false);
  fireEvent.click(confirm); await screen.findByText("No retained history.");
  assert.equal(removed, true); assert.equal(calls.some((path) => path.includes("/api/projects/")), false);
});

test("per-Project drafts survive A to B to A navigation with a pending read", async () => {
  const state = fixture(); const transport = globalThis.fetch; let release: (() => void) | undefined;
  let delay = false;
  globalThis.fetch = async (input, init) => {
    if (String(input) === `/api/projects/${projectId}/context` && delay) { delay = false; await new Promise<void>((resolve) => { release = resolve; }); }
    if (String(input).includes("project_other")) return Response.json({ project: { id: "project_other", name: "Other", revision: 1, status: "active" }, current: null, versions: [], staged: [], grants: [] });
    return transport(input, init);
  };
  render(<DraftWorkspace />); fireEvent.click(screen.getByRole("button", { name: "Open context" }));
  const input = await screen.findByLabelText("Goals and constraints"); fireEvent.change(input, { target: { value: "Unpublished workbench goals" } });
  delay = true; fireEvent.click(screen.getByRole("button", { name: "Refresh context" }));
  await waitFor(() => assert.equal(typeof release, "function"));
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" })); fireEvent.click(screen.getByRole("button", { name: "Open context" }));
  assert.equal((await screen.findByLabelText("Goals and constraints") as HTMLTextAreaElement).value, "");
  release?.();
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" })); fireEvent.click(screen.getByRole("button", { name: "Open context" }));
  assert.equal((await screen.findByLabelText("Goals and constraints") as HTMLTextAreaElement).value, "Unpublished workbench goals");
  assert.equal((screen.getByLabelText("floorplan.md") as HTMLInputElement).checked, true);
  assert.equal(state.calls.some((call) => call.body), false);
});

test("upload completion after navigation belongs to its original Project draft", async () => {
  fixture(); const transport = globalThis.fetch; let release: (() => void) | undefined; let uploaded = false;
  const staged = { ...file, id: `attachment_${"d".repeat(32)}`, name: "measurements.txt", state: "staged", expires_at: "2026-09-22T02:00:00Z" };
  globalThis.fetch = async (input, init) => {
    const path = String(input);
    if (path.endsWith("/files")) { await new Promise<void>((resolve) => { release = resolve; }); uploaded = true; return Response.json({ file: staged }); }
    if (path.includes("project_other")) return Response.json({ project: { id: "project_other", name: "Other", revision: 1, status: "active" }, current: null, versions: [], staged: [], grants: [] });
    const response = await transport(input, init);
    if (uploaded && path.endsWith("/context")) { const value = await response.json(); value.staged = [staged]; return Response.json(value); }
    return response;
  };
  render(<DraftWorkspace />); fireEvent.click(screen.getByRole("button", { name: "Open context" }));
  const input = await screen.findByLabelText("Goals and constraints"); fireEvent.change(input, { target: { value: "Keep these measurements" } });
  fireEvent.change(screen.getByLabelText("Add reference file"), { target: { files: [new File(["plan"], "measurements.txt", { type: "text/plain" })] } });
  await waitFor(() => assert.equal(typeof release, "function"));
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" })); fireEvent.click(screen.getByRole("button", { name: "Open context" }));
  await screen.findByLabelText("Goals and constraints"); release?.();
  await waitFor(() => assert.equal(uploaded, true));
  assert.equal(screen.queryByLabelText("measurements.txt"), null);
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" })); fireEvent.click(screen.getByRole("button", { name: "Open context" }));
  assert.equal((await screen.findByLabelText("Goals and constraints") as HTMLTextAreaElement).value, "Keep these measurements");
  assert.equal((screen.getByLabelText("measurements.txt") as HTMLInputElement).checked, true);
});
