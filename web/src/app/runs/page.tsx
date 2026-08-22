import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { FoundationState, Panel } from "../route-frame";

export const metadata: Metadata = { title: "Runs · Mentat" };

export default function RunsPage() {
  return (
    <AppShell route="/runs">
      <Panel eyebrow="Migration boundary" title="Run workspace">
        <FoundationState
          detail="This route is ready for the runtime-neutral run projection planned for a later slice."
          label="Waiting for the Runs data slice"
        />
      </Panel>
    </AppShell>
  );
}
