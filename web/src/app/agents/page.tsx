import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { Panel } from "../route-frame";

export const metadata: Metadata = { title: "Agents · Mentat" };

export default function AgentsPage() {
  return (
    <AppShell route="/agents">
      <Panel eyebrow="Canonical registry" title="Agent workspace">
        <section aria-live="polite" className="agents-workspace" data-agents-root data-agents-state="loading">
          <div className="agents-toolbar">
            <p className="agents-summary" data-agents-summary>Loading canonical Agents…</p>
            <button className="agent-refresh" data-agents-refresh disabled type="button">
              Refresh
            </button>
          </div>
          <div className="agents-list" data-agents-list />
        </section>
      </Panel>
    </AppShell>
  );
}
