import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { JSDOM } from "jsdom";
import { useState } from "react";
import type { DeliverableDraft } from "../src/app/tasks/project-deliverable-editor.tsx";
import type { DeliverableSlot } from "../src/lib/project-deliverable-contract.ts";

const origin = "http://127.0.0.1:8890";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: `${origin}/tasks`, pretendToBeVisual: true });
for (const name of ["document", "HTMLElement", "MouseEvent", "MutationObserver", "Node", "navigator", "window"] as const) Object.defineProperty(globalThis, name, { configurable: true, value: dom.window[name] });
Object.defineProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT", { configurable: true, value: true, writable: true });
const { cleanup, fireEvent, render, screen, waitFor } = await import("@testing-library/react");
const { ProjectDeliverableEditor, RetiredDeliverableHistory } = await import("../src/app/tasks/project-deliverable-editor.tsx");
const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });
const projectId = "project_garage";
const labels = { layout: "Garage layout", products: "Products and sources", steps: "Implementation order" } as const;

function fixture() {
  const calls: Array<{ path: string; body: Record<string, unknown> | null }> = [];
  const slots = new Map<DeliverableSlot, { id: string; slot: DeliverableSlot; head_revision: number; versions: Array<Record<string, unknown>> }>();
  const state = { calls, slots, failPublish: false, failRefreshAfterPublish: false, paginateHistory: false, advanceAfterPublish: false };
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), origin); const path = url.pathname;
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null;
    calls.push({ path, body });
    if (path === `/api/projects/${projectId}/deliverables` && init?.method === "POST") {
      if (state.failPublish) return Response.json({ schema_version: 1, status: "revision_conflict" }, { status: 409 });
      const kind = body!.slot as DeliverableSlot, previous = slots.get(kind);
      const revision = (previous?.head_revision ?? 0) + 1;
      const id = `deliverable_version_${String(revision).repeat(32)}`;
      const current = { id, revision, origin: "owner_edit", source_version_id: body!.source_version_id, content: body!.content,
        created_at: 1790035200 + revision, preview_attachment_id: kind === "layout" ? `attachment_${"a".repeat(32)}` : null };
      slots.set(kind, { id: previous?.id ?? `deliverable_${({ layout: "a", products: "b", steps: "c" } as const)[kind].repeat(32)}`, slot: kind,
        head_revision: revision, versions: [current, ...(previous?.versions.map((value) => ({ ...value, content: null })) ?? [])] });
      if (state.advanceAfterPublish) {
        slots.set(kind, { ...slots.get(kind)!, head_revision: revision + 1, versions: [
          { ...current, id: `deliverable_version_${"e".repeat(32)}`, revision: revision + 1, source_version_id: id, created_at: 1790035200 + revision + 1 },
          { ...current, content: null },
        ] });
      }
      return Response.json({ slot: kind, slot_id: slots.get(kind)!.id, version_id: id, revision, origin: "owner_edit", preview_attachment_id: current.preview_attachment_id });
    }
    if (path === `/api/projects/${projectId}/deliverables`) return state.failRefreshAfterPublish && slots.size ? Response.json({ schema_version: 1, status: "unavailable" }, { status: 503 }) : Response.json({ project: { id: projectId, name: "Garage", revision: 1, status: "active" }, slots: [...slots.values()] });
    if (path === "/api/projects/project_other/deliverables") return Response.json({ project: { id: "project_other", name: "Other", revision: 1, status: "active" }, slots: [] });
    if (path.startsWith(`/api/projects/${projectId}/deliverables/`)) {
      const id = path.split("/").at(-1); const found = [...slots.values()].flatMap((item) => item.versions.map((value) => ({ ...value, id: value["id"], slot: item.slot }))).find((item) => item.id === id);
      if (!found) throw new Error(`Missing version ${id}`);
      return Response.json({ ...found, project_id: projectId });
    }
    if (path === "/api/deliverables/history") {
      if (state.paginateHistory) {
        const offset = Number(url.searchParams.get("offset") ?? 0);
        const count = offset === 0 ? 50 : 1;
        return Response.json({ versions: Array.from({ length: count }, (_, index) => ({ id: `deliverable_version_${(offset + index).toString(16).padStart(32, "0")}`, project_id: "old_garage", slot: "steps", revision: 1, origin: "owner_edit", created_at: 1790035200 + offset + index })), next_offset: offset === 0 ? 50 : null });
      }
      return Response.json({ versions: [{ id: `deliverable_version_${"d".repeat(32)}`, project_id: "old_garage", slot: "steps", revision: 1, origin: "owner_edit", created_at: 1790035200 }], next_offset: null });
    }
    if (path.startsWith("/api/deliverables/")) return Response.json({ id: `deliverable_version_${"d".repeat(32)}`, project_id: "old_garage", slot: "steps", revision: 1, origin: "owner_edit", source_version_id: null,
      content: { notes: "Older order", steps: [{ id: "measure", title: "Measure old room", details: "Keep record", after: [] }] }, created_at: 1790035200, preview_attachment_id: null });
    throw new Error(`Unexpected request ${path}`);
  };
  return state;
}
function Workspace() {
  const [drafts, setDrafts] = useState<Partial<Record<DeliverableSlot, DeliverableDraft | null>>>({});
  return <ProjectDeliverableEditor projectId={projectId} drafts={drafts} onDraftChange={(slot, update) => setDrafts((current) => ({ ...current, [slot]: update(current[slot] ?? null) }))} />;
}
async function open() { render(<Workspace />); fireEvent.click(screen.getByRole("button", { name: "Open results" })); await screen.findByRole("button", { name: "Create result" }); }

test("owner builds all three garage results without starting any Agent work", async () => {
  const state = fixture(); await open();
  fireEvent.click(screen.getByRole("button", { name: "Create result" }));
  assert.equal((screen.getByRole("button", { name: "Save result version" }) as HTMLButtonElement).disabled, true);
  fireEvent.change(screen.getByLabelText("Garage width (mm)"), { target: { value: "6000" } });
  fireEvent.change(screen.getByLabelText("Garage depth (mm)"), { target: { value: "5000" } });
  fireEvent.click(screen.getByRole("button", { name: "Add object" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Workbench" } });
  fireEvent.click(screen.getByRole("button", { name: "Save result version" }));
  await screen.findByText("Garage layout saved as a new version. No Agent work was started.");
  assert.equal((state.slots.get("layout")!.versions[0].content as { width_mm: number }).width_mm, 6000);
  assert.equal(screen.getByRole("img", { name: "Saved dimensioned garage layout" }).getAttribute("src"), `/api/deliverables/${state.slots.get("layout")!.versions[0].id}/preview`);
  fireEvent.click(screen.getByRole("button", { name: labels.products }));
  fireEvent.click(screen.getByRole("button", { name: "Create result" }));
  fireEvent.click(screen.getByRole("button", { name: "Add product" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Wall shelf" } });
  fireEvent.change(screen.getByLabelText("HTTPS source link"), { target: { value: "https://example.com/shelf" } });
  fireEvent.click(screen.getByRole("button", { name: "Save result version" }));
  await screen.findByText("Products and sources saved as a new version. No Agent work was started.");
  assert.equal(screen.getByRole("link", { name: "Source" }).getAttribute("href"), "https://example.com/shelf");
  fireEvent.click(screen.getByRole("button", { name: labels.steps }));
  fireEvent.click(screen.getByRole("button", { name: "Create result" }));
  fireEvent.click(screen.getByRole("button", { name: "Add step" }));
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Measure the garage" } });
  fireEvent.click(screen.getByRole("button", { name: "Save result version" }));
  await screen.findByText("Implementation order saved as a new version. No Agent work was started.");
  assert.equal(state.slots.get("steps")!.head_revision, 1);
  assert.equal(state.calls.some((call) => /run|dispatch|turn/u.test(call.path)), false);
});

test("invalid product links and an uncertain save keep the owner's draft", async () => {
  const state = fixture(); await open();
  fireEvent.click(screen.getByRole("button", { name: labels.products }));
  fireEvent.click(screen.getByRole("button", { name: "Create result" }));
  fireEvent.click(screen.getByRole("button", { name: "Add product" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Wall shelf" } });
  fireEvent.change(screen.getByLabelText("HTTPS source link"), { target: { value: "https://127.0.0.01/" } });
  assert.equal((screen.getByRole("button", { name: "Save result version" }) as HTMLButtonElement).disabled, true);
  fireEvent.change(screen.getByLabelText("HTTPS source link"), { target: { value: "https://example.com/shelf" } });
  state.failPublish = true;
  fireEvent.click(screen.getByRole("button", { name: "Save result version" }));
  await screen.findByText(/draft is preserved/u);
  assert.equal((screen.getByRole("button", { name: "Create result" }) as HTMLButtonElement).disabled, true);
  assert.equal((screen.getByLabelText("HTTPS source link") as HTMLInputElement).value, "https://example.com/shelf");
  assert.equal(state.slots.size, 0);
});

test("a verified save with failed readback keeps the draft until exact reconciliation", async () => {
  const state = fixture(); await open();
  fireEvent.click(screen.getByRole("button", { name: "Create result" }));
  fireEvent.change(screen.getByLabelText("Garage width (mm)"), { target: { value: "6000" } });
  fireEvent.change(screen.getByLabelText("Garage depth (mm)"), { target: { value: "5000" } });
  state.failRefreshAfterPublish = true;
  fireEvent.click(screen.getByRole("button", { name: "Save result version" }));
  await screen.findByText(/Version 1 was accepted, but the saved list could not refresh/u);
  assert.equal((screen.getByLabelText("Garage width (mm)") as HTMLInputElement).value, "6000");
  assert.equal((screen.getByRole("button", { name: "Save result version" }) as HTMLButtonElement).disabled, true);
  assert.equal(state.slots.get("layout")?.head_revision, 1);
  state.failRefreshAfterPublish = false;
  fireEvent.click(screen.getByRole("button", { name: "Refresh results" }));
  await screen.findByRole("button", { name: "Edit latest version" });
  await waitFor(() => assert.equal(screen.queryByLabelText("Garage width (mm)"), null));
  assert.equal(screen.getByRole("img", { name: "Saved dimensioned garage layout" }).getAttribute("src"), `/api/deliverables/${state.slots.get("layout")!.versions[0].id}/preview`);
});

test("a newer owner version can become current before this device reads back its accepted save", async () => {
  const state = fixture(); await open();
  fireEvent.click(screen.getByRole("button", { name: "Create result" }));
  fireEvent.change(screen.getByLabelText("Garage width (mm)"), { target: { value: "6000" } });
  fireEvent.change(screen.getByLabelText("Garage depth (mm)"), { target: { value: "5000" } });
  state.advanceAfterPublish = true;
  fireEvent.click(screen.getByRole("button", { name: "Save result version" }));
  await screen.findByText("Version 1 was saved, and a newer version is now current. Review the history before editing.");
  assert.equal(screen.queryByLabelText("Garage width (mm)"), null);
  assert.equal((screen.getByRole("button", { name: "Edit latest version" }) as HTMLButtonElement).disabled, false);
  assert.equal(screen.getAllByRole("button", { name: /View version/u }).length, 2);
});

test("switching Projects preserves a staged layout without publishing it", async () => {
  const state = fixture();
  function Switching() {
    const [selected, setSelected] = useState(projectId);
    const [drafts, setDrafts] = useState<Record<string, Partial<Record<DeliverableSlot, DeliverableDraft | null>>>>({});
    return <><button onClick={() => setSelected(selected === projectId ? "project_other" : projectId)}>Switch Project</button><ProjectDeliverableEditor key={selected} projectId={selected} drafts={drafts[selected]} onDraftChange={(slot, update) => setDrafts((current) => ({ ...current, [selected]: { ...current[selected], [slot]: update(current[selected]?.[slot] ?? null) } }))} /></>;
  }
  render(<Switching />);
  fireEvent.click(screen.getByRole("button", { name: "Open results" }));
  fireEvent.click(await screen.findByRole("button", { name: "Create result" }));
  fireEvent.change(screen.getByLabelText("Layout notes"), { target: { value: "Keep the bike path open" } });
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" }));
  fireEvent.click(screen.getByRole("button", { name: "Switch Project" }));
  fireEvent.click(screen.getByRole("button", { name: "Open results" }));
  await screen.findByText(/Enter measured dimensions/u);
  assert.equal((screen.getByLabelText("Layout notes") as HTMLTextAreaElement).value, "Keep the bike path open");
  assert.equal(state.calls.some((call) => call.body?.slot === "layout"), false);
});

test("retired Project results stay separate from current Projects", async () => {
  fixture(); render(<RetiredDeliverableHistory />);
  fireEvent.click(screen.getByRole("button", { name: "Retained Project results" }));
  fireEvent.click(await screen.findByRole("button", { name: "View retained version" }));
  await waitFor(() => assert.match(screen.getByLabelText("Retained result version").textContent ?? "", /Measure old room/u));
});

test("retained history pages through every saved version without dropping older results", async () => {
  const state = fixture(); state.paginateHistory = true; render(<RetiredDeliverableHistory />);
  fireEvent.click(screen.getByRole("button", { name: "Retained Project results" }));
  await waitFor(() => assert.equal(screen.getAllByRole("button", { name: "View retained version" }).length, 50));
  fireEvent.click(screen.getByRole("button", { name: "Load more retained results" }));
  await waitFor(() => assert.equal(screen.getAllByRole("button", { name: "View retained version" }).length, 51));
  assert.equal(screen.queryByRole("button", { name: "Load more retained results" }), null);
  assert.ok(state.calls.some((call) => call.path === "/api/deliverables/history"));
});

test("saved products download as Markdown with the exact reviewed source link", async () => {
  fixture(); await open();
  fireEvent.click(screen.getByRole("button", { name: labels.products }));
  fireEvent.click(screen.getByRole("button", { name: "Create result" }));
  fireEvent.click(screen.getByRole("button", { name: "Add product" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Wall shelf" } });
  fireEvent.change(screen.getByLabelText("HTTPS source link"), { target: { value: "https://example.com/shelf" } });
  fireEvent.click(screen.getByRole("button", { name: "Save result version" }));
  const download = await screen.findByRole("button", { name: "Download product document" });
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL, click = dom.window.HTMLAnchorElement.prototype.click;
  let blob: Blob | null = null, filename = "";
  URL.createObjectURL = (value: Blob) => { blob = value; return "blob:garage-document"; };
  URL.revokeObjectURL = () => undefined;
  dom.window.HTMLAnchorElement.prototype.click = function () { filename = this.download; };
  try {
    fireEvent.click(download);
    assert.equal(filename, "garage-products.md");
    assert.ok(blob);
    assert.match(await (blob as Blob).text(), /\[Source\]\(https:\/\/example\.com\/shelf\)/u);
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; dom.window.HTMLAnchorElement.prototype.click = click; }
});
