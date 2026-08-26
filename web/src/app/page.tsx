import { AppShell } from "./app-shell";

import { HomeConsole } from "./home-console";

export const dynamic = "force-dynamic";

export default function HomePage() {
  return (
    <AppShell homeConsole route="/">
      <HomeConsole />
    </AppShell>
  );
}
