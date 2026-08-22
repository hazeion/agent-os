import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { Panel } from "../route-frame";

export const metadata: Metadata = { title: "Tasks · Mentat" };

export default function TasksPage() {
  return (
    <AppShell route="/tasks">
      <Panel eyebrow="SQLite authority" title="Task workspace">
        <section aria-live="polite" className="tasks-workspace" data-tasks-root data-tasks-state="loading">
          <div className="tasks-toolbar">
            <p className="tasks-summary" data-tasks-summary>Loading current Tasks…</p>
            <button className="task-refresh" data-tasks-refresh disabled type="button">Refresh</button>
          </div>
          <div className="tasks-list" data-tasks-list />
        </section>
      </Panel>
    </AppShell>
  );
}
