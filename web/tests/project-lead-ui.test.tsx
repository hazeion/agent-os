import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://127.0.0.1:8890/tasks", pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { render, screen, fireEvent, cleanup } = await import("@testing-library/react");
const { ProjectLeadEditor } = await import("../src/app/tasks/project-lead-editor.tsx");
const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });

test("owner can select a lead without dispatching work", async () => {
  const token = "a".repeat(64), paths: string[] = [];
  const initial = { project_id: "project_garage", project_revision: 1, revision: 0, id: null, agent_id: null, agent_name: null,
    status: "unassigned", reasons: [], proposal_available: false, choices: [{ id: "agent_research", name: "Research", context_bound: false, selection_token: token }], clear_token: token };
  globalThis.fetch = async (input, init) => {
    paths.push(String(input));
    if (init?.method === "POST") { assert.deepEqual(JSON.parse(String(init.body)), { agent_id: "agent_research", expected_project_revision: 1, expected_lead_revision: 0, selection_token: token });
      return Response.json({ ...initial, revision: 1, id: `lead_role_${"b".repeat(32)}`, agent_id: "agent_research", agent_name: "Research", status: "unready", reasons: ["context_grant_needed"] }); }
    return Response.json(initial);
  };
  render(<ProjectLeadEditor projectId="project_garage" />);
  fireEvent.click(screen.getByRole("button", { name: "Open lead" }));
  const selector = await screen.findByLabelText("Lead Agent");
  fireEvent.change(selector, { target: { value: "agent_research" } });
  fireEvent.click(screen.getByRole("button", { name: "Save lead" }));
  await screen.findByText(/Lead selected. Save Project context/u);
  assert.equal(paths.length, 2);
  assert.ok(paths.every((path) => path === "/api/projects/project_garage/lead"));
  assert.match(screen.getByLabelText("Project lead").textContent ?? "", /does not start work/u);
});

test("duplicate Agent names remain distinguishable and a deleted lead can be cleared", async () => {
  const token = "a".repeat(64), role = `lead_role_${"b".repeat(32)}`;
  const initial = { project_id: "project_garage", project_revision: 1, revision: 1, id: role,
    agent_id: "agent_removed", agent_name: null, status: "stale", reasons: ["agent_changed", "context_grant_needed"],
    proposal_available: false, choices: [
      { id: "agent_one", name: "Research", context_bound: false, selection_token: token },
      { id: "agent_two", name: "Research", context_bound: false, selection_token: token },
    ], clear_token: token };
  globalThis.fetch = async (_input, init) => init?.method === "POST"
    ? Response.json({ ...initial, revision: 2, id: `lead_role_${"c".repeat(32)}`, agent_id: null, status: "unassigned", reasons: [] })
    : Response.json(initial);
  render(<ProjectLeadEditor projectId="project_garage" />);
  fireEvent.click(screen.getByRole("button", { name: "Open lead" }));
  const selector = await screen.findByLabelText("Lead Agent") as HTMLSelectElement;
  assert.match(selector.textContent, /Research \(agent_one\)/u);
  assert.match(selector.textContent, /Research \(agent_two\)/u);
  assert.match(selector.textContent, /agent_removed · unavailable/u);
  fireEvent.change(selector, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Clear lead" }));
  await screen.findByText("Project lead cleared.");
  assert.match(screen.getByLabelText("Project lead").textContent ?? "", /No Project lead/u);
});

test("a deleted lead can be cleared when no Agents remain", async () => {
  const token = "a".repeat(64), initial = { project_id: "project_garage", project_revision: 1, revision: 1, id: `lead_role_${"b".repeat(32)}`,
    agent_id: "agent_removed", agent_name: null, status: "stale", reasons: ["agent_changed", "context_grant_needed"],
    proposal_available: false, choices: [], clear_token: token };
  let writes = 0;
  globalThis.fetch = async (_input, init) => {
    if (init?.method === "POST") { writes++; assert.equal(JSON.parse(String(init.body)).agent_id, null);
      return Response.json({ ...initial, revision: 2, id: `lead_role_${"c".repeat(32)}`, agent_id: null, status: "unassigned", reasons: [] }); }
    return Response.json(initial);
  };
  render(<ProjectLeadEditor projectId="project_garage" />);
  fireEvent.click(screen.getByRole("button", { name: "Open lead" }));
  const selector = await screen.findByLabelText("Lead Agent") as HTMLSelectElement;
  assert.equal(selector.disabled, false);
  fireEvent.change(selector, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Clear lead" }));
  await screen.findByText("Project lead cleared.");
  assert.equal(writes, 1);
});
