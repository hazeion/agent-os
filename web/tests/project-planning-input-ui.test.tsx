import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
import { useState } from "react";
import type { ProjectPlanningInputDraft } from "../src/app/tasks/project-planning-input-editor.tsx";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://127.0.0.1:8890/tasks", pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { render, screen, fireEvent, cleanup } = await import("@testing-library/react");
const { ProjectPlanningInputEditor } = await import("../src/app/tasks/project-planning-input-editor.tsx");
const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });

const projectId = "project_garage", roleId = `lead_role_${"a".repeat(32)}`, contextId = `project_context_${"b".repeat(32)}`;
const inputId = `project_input_${"c".repeat(32)}`;
const file = { id: `attachment_${"d".repeat(32)}`, name: "floorplan.md", mime_type: "text/markdown", kind: "text", byte_size: 12,
  state: "attached", created_at: "2026-09-29T00:00:00Z", expires_at: null, available: true };
const context = { id: contextId, revision: 1, created_at: 1790640000, project_id: projectId,
  brief: "Keep bicycle access clear", retired: false, current: true, files: [file], prune_blocked: "current_version" };
const initial = { project: { id: projectId, name: "Garage", revision: 1, status: "active" },
  lead: { id: roleId, revision: 1, agent_id: "agent_research", agent_name: "Research", status: "context_bound", reasons: [] },
  context, grant_revision: 1, input_revision: 0, scope_token: "1".repeat(64), selection_token: "2".repeat(64),
  save_available: true, version: null, versions: [] };
const saved = { ...initial, input_revision: 1, selection_token: "3".repeat(64),
  version: { id: inputId, revision: 1, project_revision: 1, lead_role_id: roleId, agent_id: "agent_research",
    context_id: contextId, context_revision: 1, project_brief: context.brief, grant_revision: 1,
    instructions: "Use the measured layout.", created_at: 1790641000, files: [file] },
  versions: [{ id: inputId, revision: 1, context_id: contextId, created_at: 1790641000 }] };

test("owner saves only an exact Project input and no Run is started", async () => {
  const calls: Array<{ path: string; method: string; body: Record<string, unknown> | null }> = []; let committed = false;
  globalThis.fetch = async (input, init) => {
    const path = String(input), method = init?.method ?? "GET", body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null;
    calls.push({ path, method, body });
    if (method === "POST") { committed = true; assert.match(String(body?.action_id), /^project_input_action_[0-9a-f]{32}$/u);
      assert.equal(body?.project_id, undefined); assert.deepEqual(body?.attachment_ids, [file.id]);
      return Response.json({ input_id: inputId, revision: 1, status: "saved" }); }
    return Response.json(committed ? saved : initial);
  };
  render(<ProjectPlanningInputEditor projectId={projectId} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare planning inputs" }));
  const textarea = await screen.findByLabelText("Instructions for the Project lead");
  fireEvent.change(textarea, { target: { value: "Use the measured layout." } });
  fireEvent.click(screen.getByRole("checkbox", { name: "floorplan.md" }));
  fireEvent.click(screen.getByRole("button", { name: "Save Project input version" }));
  await screen.findByText("Saved Project planning input version 1. No Agent work was started.");
  assert.equal(calls.filter((call) => call.method === "POST").length, 1);
  assert.ok(calls.every((call) => call.path === `/api/projects/${projectId}/planning-inputs`));
  assert.match(screen.getByLabelText("Project planning inputs").textContent ?? "", /Lead proposals are unavailable/u);
});

test("lost response retains one action and reconciles it without another Save", async () => {
  let postCount = 0, actionId = "", committed = false;
  globalThis.fetch = async (input, init) => {
    const path = String(input);
    if (init?.method === "POST") { postCount++; actionId = String((JSON.parse(String(init.body)) as Record<string, unknown>).action_id); committed = true; throw new TypeError("lost response"); }
    if (path.includes("/actions/")) { assert.ok(path.includes(actionId)); return Response.json({ status: "committed_needs_review", input_id: inputId, revision: 1 }); }
    return Response.json(committed ? saved : initial);
  };
  render(<ProjectPlanningInputEditor projectId={projectId} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare planning inputs" }));
  await screen.findByLabelText("Instructions for the Project lead");
  fireEvent.click(screen.getByRole("button", { name: "Save Project input version" }));
  await screen.findByText(/could not verify the save/u);
  assert.equal((screen.getByRole("button", { name: "Save Project input version" }) as HTMLButtonElement).disabled, true);
  fireEvent.click(screen.getByRole("button", { name: "Check saved action" }));
  await screen.findByText(/Input version 1 committed/u);
  assert.equal(postCount, 1);
});

test("a recreated Project scope blocks an old local draft", async () => {
  let newScope = false;
  globalThis.fetch = async () => Response.json(newScope ? { ...initial, scope_token: "f".repeat(64) } : initial);
  render(<ProjectPlanningInputEditor projectId={projectId} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare planning inputs" }));
  const textarea = await screen.findByLabelText("Instructions for the Project lead") as HTMLTextAreaElement;
  fireEvent.change(textarea, { target: { value: "Keep the old note" } });
  newScope = true; fireEvent.click(screen.getByRole("button", { name: "Refresh planning inputs" }));
  await screen.findByText(/different Project incarnation/u);
  assert.equal(textarea.value, "Keep the old note");
  assert.equal((screen.getByRole("button", { name: "Save Project input version" }) as HTMLButtonElement).disabled, true);
});

test("uncertain action ID and exact body survive Project navigation and remount", async () => {
  const submitted: Record<string, unknown>[] = [];
  globalThis.fetch = async (input, init) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>; submitted.push(body);
      if (submitted.length === 1) throw new TypeError("lost response");
      return Response.json({ input_id: inputId, revision: 1, status: "committed_needs_review" });
    }
    return Response.json(submitted.length > 1 ? saved : initial);
  };
  function Workspace() {
    const [project, setProject] = useState(projectId);
    const [drafts, setDrafts] = useState<Record<string, ProjectPlanningInputDraft | null>>({});
    return <><button type="button" onClick={() => setProject(project === projectId ? "project_other" : projectId)}>Switch Project</button>
      <ProjectPlanningInputEditor key={project} projectId={project} draft={drafts[project]}
        onDraftChange={(update) => setDrafts((current) => ({ ...current, [project]: update(current[project] ?? null) }))} /></>;
  }
  render(<Workspace />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare planning inputs" }));
  await screen.findByLabelText("Instructions for the Project lead");
  fireEvent.click(screen.getByRole("button", { name: "Save Project input version" }));
  await screen.findByText(/could not verify the save/u);
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" }));
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" }));
  fireEvent.click(screen.getByRole("button", { name: "Prepare planning inputs" }));
  await screen.findByRole("button", { name: "Retry exact save" });
  fireEvent.click(screen.getByRole("button", { name: "Retry exact save" }));
  await screen.findByText(/committed earlier/u);
  assert.equal(submitted.length, 2);
  assert.deepEqual(submitted[1], submitted[0]);
});

test("read failure and post-commit refresh failure do not claim an unknown Save", async () => {
  globalThis.fetch = async () => { throw new TypeError("read failed"); };
  render(<ProjectPlanningInputEditor projectId={projectId} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare planning inputs" }));
  await screen.findByText(/could not load Project planning inputs/u);
  cleanup();
  let reads = 0;
  globalThis.fetch = async (_input, init) => {
    if (init?.method === "POST") return Response.json({ input_id: inputId, revision: 1, status: "saved" });
    reads++; if (reads > 1) throw new TypeError("refresh failed");
    return Response.json(initial);
  };
  render(<ProjectPlanningInputEditor projectId={projectId} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare planning inputs" }));
  await screen.findByLabelText("Instructions for the Project lead");
  fireEvent.click(screen.getByRole("button", { name: "Save Project input version" }));
  await screen.findByText(/Input version 1 committed, but the current view could not load/u);
  assert.equal(screen.queryByText(/could not verify the save/u), null);
  assert.equal((screen.getByRole("button", { name: "Save Project input version" }) as HTMLButtonElement).disabled, true);
});

test("same-incarnation explicit rebase preserves typed instructions", async () => {
  let changed = false;
  globalThis.fetch = async () => Response.json(changed ? { ...initial, selection_token: "f".repeat(64) } : initial);
  render(<ProjectPlanningInputEditor projectId={projectId} />);
  fireEvent.click(screen.getByRole("button", { name: "Prepare planning inputs" }));
  const textarea = await screen.findByLabelText("Instructions for the Project lead") as HTMLTextAreaElement;
  fireEvent.change(textarea, { target: { value: "Keep this owner note" } });
  changed = true; fireEvent.click(screen.getByRole("button", { name: "Refresh planning inputs" }));
  await screen.findByText(/Project access or saved inputs changed/u);
  fireEvent.click(screen.getByRole("button", { name: "Use current access" }));
  assert.equal(textarea.value, "Keep this owner note");
});
