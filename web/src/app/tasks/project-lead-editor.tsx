"use client";

import { useEffect, useRef, useState } from "react";
import type { ProjectLead } from "@/lib/project-lead-contract";
import { projectLeads, PublicProjectLeadError } from "@/lib/public-project-leads";

function errorMessage(error: unknown): string {
  if (error instanceof PublicProjectLeadError && ["project_changed", "revision_conflict", "selection_changed", "agent_unavailable"].includes(error.code)) return "The Project or Agent changed. Refresh the lead selection before saving again.";
  if (error instanceof PublicProjectLeadError && error.code === "capacity") return "The saved lead history is full.";
  return "Mentat could not verify the selection. Refresh to check the saved lead before deciding what to do next.";
}

export function ProjectLeadEditor({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [view, setView] = useState<ProjectLead | null>(null), [selected, setSelected] = useState<string | null>(null);
  const locked = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function refresh() {
    const next = await projectLeads("project", { project_id: projectId });
    if (mounted.current) { setView(next); setSelected(next.agent_id); }
  }
  async function perform(action: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setNotice("");
    try { await action(); } catch (error) { if (mounted.current) setNotice(errorMessage(error)); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function save() {
    if (!view) return;
    const choice = selected === null ? null : view.choices.find((item) => item.id === selected);
    if (selected !== null && !choice) return;
    const saved = await projectLeads("select", { project_id: projectId, agent_id: selected,
      expected_project_revision: view.project_revision, expected_lead_revision: view.revision,
      selection_token: choice?.selection_token ?? view.clear_token });
    if (mounted.current) { setView(saved); setSelected(saved.agent_id); setNotice(saved.status === "context_bound"
      ? "Lead selected. Proposal work is not available yet."
      : saved.status === "unassigned" ? "Project lead cleared." : "Lead selected. Save Project context and grant this Agent access before proposal work can be enabled."); }
  }
  const changed = view && selected !== view.agent_id;
  const reselect = view && selected !== null && selected === view.agent_id && view.status !== "context_bound";
  return <section className="project-context-panel" aria-label="Project lead">
    <div className="project-context-heading"><h3>Project lead</h3><button type="button" disabled={busy} aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void perform(refresh); }}>{open ? "Hide lead" : "Open lead"}</button></div>
    {open ? <div className="project-context-body">
      <p>Choose one Agent to propose a Project plan. You can still assign Agents to Tasks yourself. Selecting a lead does not start work or grant access.</p>
      <p role="status" aria-live="polite">{busy ? "Working…" : notice}</p>
      <div className="project-context-actions"><button type="button" disabled={busy} onClick={() => void perform(refresh)}>Refresh lead</button></div>
      {view ? <>
        <p>Current selection: {view.agent_id ? `${view.agent_name ?? "Agent"} (${view.agent_id}) · ${view.status === "context_bound" ? "Context access ready" : view.status === "unready" ? "Needs context access" : "Needs review"}` : "No Project lead"}</p>
        {view.reasons.length ? <p>{view.status === "unready" ? "Publish Project context and grant this Agent access, then reselect the lead." : "The saved Project, Agent, context, or grant changed. Review and reselect the lead."}</p> : null}
        <label>Lead Agent<select value={selected ?? ""} disabled={busy} onChange={(event) => setSelected(event.target.value || null)}><option value="">No lead</option>{selected && !view.choices.some((item) => item.id === selected) ? <option value={selected} disabled>{selected} · unavailable</option> : null}{view.choices.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.id}){item.context_bound ? " · context access ready" : " · needs context access"}</option>)}</select></label>
        <div className="project-context-actions"><button type="button" disabled={busy || (!changed && !reselect) || (selected !== null && !view.choices.some((item) => item.id === selected))} onClick={() => void perform(save)}>{reselect ? "Reselect lead" : selected === null ? "Clear lead" : "Save lead"}</button></div>
        <p>Lead proposals and Apply are coming in a later reviewed slice. This selection has no Run or approval authority.</p>
      </> : !busy ? <p>Lead selection is unavailable. Refresh to try again.</p> : null}
    </div> : null}
  </section>;
}
