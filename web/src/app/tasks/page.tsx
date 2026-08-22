import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { FoundationState, Panel } from "../route-frame";

export const metadata: Metadata = { title: "Tasks · Mentat" };

export default function TasksPage() {
  return (
    <AppShell route="/tasks">
      <Panel eyebrow="Migration boundary" title="Task workspace">
        <FoundationState
          detail="SQLite is already authoritative. The planning UI and API connection arrive in the Tasks migration slice."
          label="Waiting for the Tasks data slice"
        />
      </Panel>
    </AppShell>
  );
}
