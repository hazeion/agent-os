import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
import { useState } from "react";
import type { TaskInputDraft } from "../src/app/tasks/project-task-input-editor.tsx";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://127.0.0.1:8890/tasks", pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { render, screen, fireEvent, waitFor, cleanup } = await import("@testing-library/react");
const { ProjectTaskInputEditor, RetiredTaskInputHistory } = await import("../src/app/tasks/project-task-input-editor.tsx");
const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });
const contextId = `project_context_${"a".repeat(32)}`, attachmentId = `attachment_${"b".repeat(32)}`, versionId = `task_input_${"c".repeat(32)}`;
const file = { id: attachmentId, name: "dimensions.md", mime_type: "text/markdown", kind: "text", byte_size: 20, state: "attached", created_at: "2026-09-22T00:00:00Z", expires_at: null, available: true };
const version = { id: versionId, revision: 1, task_revision: 1, agent_id: "agent_research", context_id: contextId, context_revision: 1, project_brief: "Use supplied dimensions", grant_revision: 1, instructions: "Keep bicycles clear", created_at: 1790035200, files: [file] };
const context = { id: contextId, revision: 1, brief: "Use supplied dimensions", created_at: 1790035200, project_id: "project_garage", retired: false, current: true, files: [file], prune_blocked: "current_version" };
function editor(taskId = "task_research") { return { task: { id: taskId, title: "Garage research", revision: 1, project_id: "project_garage", project_status: "active", assigned_agent_id: "agent_research" }, input_revision: 1, expected_task_token: "f".repeat(64), version, versions: [{ id: versionId, revision: 1, context_id: contextId, created_at: 1790035200 }], eligible_contexts: [{ context, grant_revision: 1 }] }; }
function fixture() {
  const state = { reads: 0, writes: [] as Record<string, unknown>[], changed: false, saveUncertain: false };
  globalThis.fetch = async (input, init) => {
    const url = String(input); const taskId = url.includes("task_layout") ? "task_layout" : "task_research";
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>; state.writes.push(body);
      if (state.saveUncertain) { state.changed = true; throw new Error("connection lost after commit"); }
      return Response.json({ input_id: `task_input_${"d".repeat(32)}`, revision: state.changed ? 3 : 2 });
    }
    state.reads++;
    const value = editor(taskId);
    if (state.changed && taskId === "task_research") { value.task.revision = 2; value.expected_task_token = "e".repeat(64); }
    return Response.json(value);
  };
  return state;
}
async function open() { fireEvent.click(screen.getByRole("button", { name: "Prepare inputs" })); await screen.findByLabelText("Task-specific instructions"); }

test("saving an exact selection creates a version without granting or dispatching", async () => {
  const state = fixture(); render(<ProjectTaskInputEditor taskId="task_research" />); await open();
  assert.equal(screen.getAllByText("Use supplied dimensions").length, 2);
  fireEvent.change(screen.getByLabelText("Task-specific instructions"), { target: { value: "Dimensioned layout with bicycle clearance" } });
  fireEvent.click(screen.getByRole("button", { name: "Save input version" }));
  await screen.findByText(/Saved Task input version 2/u);
  assert.deepEqual(state.writes, [{ project_id: "project_garage", agent_id: "agent_research", expected_task_revision: 1, expected_input_revision: 1, expected_task_token: "f".repeat(64), context_id: contextId, expected_grant_revision: 1, instructions: "Dimensioned layout with bicycle clearance", attachment_ids: [attachmentId] }]);
  assert.equal(state.writes.some((body) => "runtime_agent_ref" in body || "run_id" in body || "command" in body), false);
});

test("switching Tasks preserves the original draft and stale identity blocks publishing", async () => {
  const state = fixture();
  function Workspace() {
    const [taskId, setTaskId] = useState("task_research"), [drafts, setDrafts] = useState<Record<string, TaskInputDraft | null>>({});
    return <><button onClick={() => setTaskId(taskId === "task_research" ? "task_layout" : "task_research")}>Switch Task</button><ProjectTaskInputEditor key={taskId} taskId={taskId} draft={drafts[taskId]} onDraftChange={(update) => setDrafts((current) => ({ ...current, [taskId]: update(current[taskId] ?? null) }))} /></>;
  }
  render(<Workspace />); await open();
  fireEvent.change(screen.getByLabelText("Task-specific instructions"), { target: { value: "Unpublished measurements" } });
  fireEvent.click(screen.getByRole("button", { name: "Switch Task" })); await open();
  assert.equal((screen.getByLabelText("Task-specific instructions") as HTMLTextAreaElement).value, "Keep bicycles clear");
  state.changed = true;
  fireEvent.click(screen.getByRole("button", { name: "Switch Task" })); await open();
  assert.equal((screen.getByLabelText("Task-specific instructions") as HTMLTextAreaElement).value, "Unpublished measurements");
  assert.equal((screen.getByRole("button", { name: "Save input version" }) as HTMLButtonElement).disabled, true);
  fireEvent.click(screen.getByRole("button", { name: "Use current Task" }));
  assert.equal((screen.getByLabelText("Task-specific instructions") as HTMLTextAreaElement).value, "Keep bicycles clear");
  assert.equal(state.writes.length, 0);
});

test("uncertain save requires reconciliation and keeps the draft", async () => {
  const state = fixture(); state.saveUncertain = true;
  render(<ProjectTaskInputEditor taskId="task_research" />); await open();
  fireEvent.change(screen.getByLabelText("Task-specific instructions"), { target: { value: "Workbench measurements" } });
  fireEvent.click(screen.getByRole("button", { name: "Save input version" }));
  await screen.findByText(/could not verify the save/u);
  assert.equal((screen.getByRole("button", { name: "Save input version" }) as HTMLButtonElement).disabled, true);
  assert.equal((screen.getByLabelText("Task-specific instructions") as HTMLTextAreaElement).value, "Workbench measurements");
  fireEvent.click(screen.getByRole("button", { name: "Refresh Task inputs" }));
  await waitFor(() => assert.equal((screen.getByRole("button", { name: "Refresh Task inputs" }) as HTMLButtonElement).disabled, false));
  assert.equal((screen.getByRole("button", { name: "Save input version" }) as HTMLButtonElement).disabled, true);
  assert.equal(state.writes.length, 1);
});

test("saved inputs remain inspectable when their old Project grant is revoked", async () => {
  fixture(); const transport = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    const response = await transport(input, init); if (init?.method === "POST") return response;
    const data = await response.json(); data.eligible_contexts = []; return Response.json(data);
  };
  render(<ProjectTaskInputEditor taskId="task_research" />); await open();
  assert.match(screen.getByLabelText("Saved Task input version").textContent ?? "", /Project context version 1/u);
  assert.match(screen.getByLabelText("Saved Task input version").textContent ?? "", /Use supplied dimensions/u);
  const fileLink = screen.getByLabelText("Saved Task input version").querySelector("a");
  assert.equal(fileLink?.getAttribute("href"), `/api/project-context/${contextId}/files/${attachmentId}`);
  assert.equal((screen.getByRole("button", { name: "Save input version" }) as HTMLButtonElement).disabled, true);
});

test("retired inputs remain separate and require an exact removal confirmation", async () => {
  let removed = false; const calls: string[] = [];
  globalThis.fetch = async (input, init) => {
    const path = String(input); calls.push(path);
    if (path.endsWith("/history")) return Response.json({ versions: removed ? [] : [{ id: versionId, revision: 1, created_at: version.created_at, summary: "Former garage inputs" }] });
    if (path.endsWith("/prune/preview")) return Response.json({ input_id: versionId, revision: 1, file_count: 1, confirmation_id: "f".repeat(64) });
    if (path.endsWith("/prune")) { assert.equal(init?.method, "POST"); removed = true; return Response.json({ pruned: true }); }
    return Response.json(version);
  };
  render(<RetiredTaskInputHistory />);
  fireEvent.click(screen.getByRole("button", { name: "Retained Task inputs" }));
  fireEvent.click(await screen.findByRole("button", { name: "View retained input" }));
  const saved = await screen.findByLabelText("Retired Task input version");
  assert.match(saved.textContent ?? "", /Use supplied dimensions/u);
  assert.equal(saved.querySelector("a")?.getAttribute("href"), `/api/project-context/${contextId}/files/${attachmentId}`);
  fireEvent.click(screen.getByRole("button", { name: "Review input removal" }));
  const confirmation = await screen.findByRole("button", { name: "Confirm input removal" });
  assert.equal(removed, false); fireEvent.click(confirmation);
  await screen.findByText("No retained Task inputs.");
  assert.equal(removed, true);
  assert.equal(calls.some((path) => path.includes("/api/projects/")), false);
});
