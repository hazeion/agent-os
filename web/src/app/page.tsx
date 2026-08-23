import { AppShell } from "./app-shell";
import { FoundationState, Panel } from "./route-frame";

export default function HomePage() {
  return (
    <AppShell route="/">
      <div className="dashboard-grid grid min-w-0 gap-3">
        <Panel eyebrow="Current system" title="Operational status">
          <FoundationState
            detail="The Next.js workspace reads Agents, SQLite Tasks, runtime-neutral Runs, and provider status through the private Python bridge."
            label="Pivot workspace ready"
          />
        </Panel>

        <Panel eyebrow="Live workspaces" title="Connected surfaces">
          <ol className="migration-list">
            <li>
              <strong>Agents</strong>
              <span>Canonical Agent registry and provider status.</span>
            </li>
            <li>
              <strong>Tasks</strong>
              <span>SQLite-backed planning data.</span>
            </li>
            <li>
              <strong>Runs</strong>
              <span>Runtime-neutral history, timelines, and controls.</span>
            </li>
          </ol>
        </Panel>
      </div>
    </AppShell>
  );
}
