import type { Metadata, Viewport } from "next";

import "./globals.css";
import { ShellRuntimeSignal } from "./shell-runtime-signal";

export const metadata: Metadata = {
  description: "Mentat's local-first operations workspace.",
  title: "Mentat",
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#070d11",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html data-ui-shell="emerald" lang="en" suppressHydrationWarning>
      <body>
        {children}
        <ShellRuntimeSignal />
        <script data-mentat-shell-runtime defer src="/shell-runtime.js" type="module" />
      </body>
    </html>
  );
}
