import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { Panel } from "../route-frame";

export const metadata: Metadata = { title: "Runs · Mentat" };

export default function RunsPage() {
  return (
    <AppShell route="/runs">
      <Panel eyebrow="Runtime coexistence" title="Run workspace">
        <section className="runs-workspace" data-runs-root data-runs-state="loading">
          <div className="runs-toolbar">
            <p aria-atomic="true" aria-live="polite" className="runs-summary" data-runs-summary>Loading current Runs…</p>
            <button className="run-refresh" data-runs-refresh disabled type="button">Refresh</button>
          </div>
          <div className="runs-list" data-runs-list />
        </section>
      </Panel>
    </AppShell>
  );
}
