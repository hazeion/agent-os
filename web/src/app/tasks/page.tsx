import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { Panel } from "../route-frame";
import { ProjectsTasksPrototype } from "./projects-tasks-prototype";
import { ProjectsTasksWorkspace } from "./projects-tasks-workspace";

export const metadata: Metadata = { title: "Projects & Tasks · Mentat" };
export const dynamic = "force-dynamic";

type TasksPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function TasksPage({ searchParams }: TasksPageProps) {
  const parameters = await searchParams;
  const requestedVariant = typeof parameters.variant === "string" ? parameters.variant : null;
  const prototypeVariant = process.env.NODE_ENV !== "production" && ["a", "b", "c"].includes(requestedVariant ?? "")
    ? requestedVariant as "a" | "b" | "c"
    : null;
  return (
    <AppShell route="/tasks">
      <Panel eyebrow="Planning" title="Projects & Tasks">
        {prototypeVariant ? <ProjectsTasksPrototype initialVariant={prototypeVariant} /> : <ProjectsTasksWorkspace />}
      </Panel>
    </AppShell>
  );
}
