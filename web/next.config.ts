import type { NextConfig } from "next";

const staticShell = process.env.MENTAT_STATIC_FOUNDATION === "1";
const securityHeaders = [
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=()" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
];

const nextConfig: NextConfig = {
  agentRules: false,
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return {
      beforeFiles: staticShell
        ? [
            { source: "/agents", destination: "/shell/agents.html" },
            { source: "/runs", destination: "/shell/runs.html" },
          ]
        : [],
      afterFiles: [],
      fallback: [],
    };
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
