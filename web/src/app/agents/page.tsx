import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { Panel } from "../route-frame";

export const metadata: Metadata = { title: "Agents · Mentat" };

export default function AgentsPage() {
  return (
    <AppShell route="/agents">
      <Panel eyebrow="Canonical registry" title="Agent workspace">
        <div className="agents-workspace-section">
          <h2>Provider connections</h2>
          <section
            aria-live="polite"
            className="provider-connections-workspace"
            data-provider-connections-root
            data-provider-connections-state="loading"
          >
            <div className="agents-toolbar">
              <p className="agents-summary" data-provider-connections-summary>
                Loading provider connections…
              </p>
              <button
                className="agent-refresh"
                data-provider-connections-refresh
                disabled
                type="button"
              >
                Refresh
              </button>
            </div>
            <div className="provider-connections-list" data-provider-connections-list>
              <article aria-hidden="true" className="provider-connection-card provider-connection-placeholder" />
            </div>
          </section>
        </div>
        <div className="agents-workspace-section">
          <h2>Agents</h2>
          <section aria-live="polite" className="agents-workspace" data-agents-root data-agents-state="loading">
            <div className="agents-toolbar">
              <p className="agents-summary" data-agents-summary>Loading canonical Agents…</p>
              <button className="agent-refresh" data-agents-refresh disabled type="button">
                Refresh
              </button>
            </div>
            <div className="agents-list" data-agents-list />
          </section>
        </div>
      </Panel>
    </AppShell>
  );
}
