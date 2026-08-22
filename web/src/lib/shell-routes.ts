export const SHELL_ROUTES = [
  {
    href: "/",
    label: "Home",
    description: "Planning overview",
    icon: "home",
  },
  {
    href: "/agents",
    label: "Agents",
    description: "Canonical workers",
    icon: "agents",
  },
  {
    href: "/tasks",
    label: "Tasks",
    description: "Personal planning",
    icon: "tasks",
  },
  {
    href: "/runs",
    label: "Runs",
    description: "Execution history",
    icon: "runs",
  },
] as const;

export type ShellRoute = (typeof SHELL_ROUTES)[number];
export type ShellRouteHref = ShellRoute["href"];
export type ShellIconName = ShellRoute["icon"] | "menu" | "close" | "contrast";

export function getShellRoute(href: ShellRouteHref): ShellRoute {
  const route = SHELL_ROUTES.find((candidate) => candidate.href === href);

  if (!route) {
    throw new Error(`Unknown Mentat shell route: ${href}`);
  }

  return route;
}
