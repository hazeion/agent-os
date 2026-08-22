import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { FoundationState, Panel } from "../route-frame";

export const metadata: Metadata = { title: "Agents · Mentat" };

export default function AgentsPage() {
  return (
    <AppShell route="/agents">
      <Panel eyebrow="Migration boundary" title="Agent workspace">
        <FoundationState
          detail="The shared shell is in place. Canonical Agent data will connect in its own reviewed slice."
          label="Waiting for the Agents data slice"
        />
      </Panel>
    </AppShell>
  );
}
