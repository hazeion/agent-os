import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { Panel } from "../route-frame";
import { ProjectsTasksWorkspace } from "./projects-tasks-workspace";

export const metadata: Metadata = { title: "Projects & Tasks · Mentat" };
export const dynamic = "force-dynamic";

export default function TasksPage() {
  return (
    <AppShell route="/tasks">
      <Panel eyebrow="Planning" title="Projects & Tasks">
        <ProjectsTasksWorkspace />
      </Panel>
    </AppShell>
  );
}
