import type { Metadata } from "next";

import { AppShell } from "../app-shell";
import { Panel } from "../route-frame";
import { OwnerInboxWorkspace } from "./owner-inbox-workspace";

export const metadata: Metadata = { title: "Inbox · Mentat" };
export const dynamic = "force-dynamic";

export default function InboxPage() {
  return <AppShell route="/inbox"><Panel eyebrow="Your attention" title="Inbox"><OwnerInboxWorkspace /></Panel></AppShell>;
}
