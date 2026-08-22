import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  description: "Mentat's local-first Node runtime and Python Local Bridge foundation.",
  title: "Mentat Runtime Foundation",
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#06110d",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
