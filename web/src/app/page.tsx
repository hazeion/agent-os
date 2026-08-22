import { AppShell } from "./app-shell";
import { FoundationState, Panel } from "./route-frame";

export default function HomePage() {
  return (
    <AppShell route="/">
      <div className="dashboard-grid grid min-w-0 gap-3">
        <Panel eyebrow="Current slice" title="Operational focus">
          <FoundationState
            detail="The shared React shell is ready. Live planning data remains in the Python dashboard until the Tasks migration slice."
            label="Shell foundation ready"
          />
        </Panel>

        <Panel eyebrow="Next connections" title="Migration status">
          <ol className="migration-list">
            <li>
              <strong>Agents</strong>
              <span>Connect the canonical Agent registry.</span>
            </li>
            <li>
              <strong>Tasks</strong>
              <span>Move the planning workspace onto the SQLite API.</span>
            </li>
            <li>
              <strong>Runs</strong>
              <span>Add runtime-neutral execution visibility.</span>
            </li>
          </ol>
        </Panel>
      </div>
    </AppShell>
  );
}
