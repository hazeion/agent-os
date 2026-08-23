import type { NextConfig } from "next";

const staticShell = process.env.MENTAT_STATIC_FOUNDATION === "1";
const developmentRuntime = process.env.NODE_ENV === "development";
const scriptPolicy = staticShell
  ? "script-src 'self'"
  : developmentRuntime
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self' 'unsafe-inline'";
const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "base-uri 'none'",
      "connect-src 'self'",
      "font-src 'self'",
      "form-action 'self'",
      "frame-ancestors 'none'",
      "img-src 'self' data:",
      "object-src 'none'",
      scriptPolicy,
      "style-src 'self' 'unsafe-inline'",
    ].join("; "),
  },
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
            { source: "/", destination: "/shell/home.html" },
            { source: "/agents", destination: "/shell/agents.html" },
            { source: "/tasks", destination: "/shell/tasks.html" },
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
