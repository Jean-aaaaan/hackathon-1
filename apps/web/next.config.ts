import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

function apiConnectOrigins(): string[] {
  const raw = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  try {
    const u = new URL(raw);
    const http = u.origin;
    const ws = u.protocol === "https:" ? `wss://${u.host}` : `ws://${u.host}`;
    return [http, ws];
  } catch {
    return ["http://localhost:8000", "ws://localhost:3000"];
  }
}

const apiOrigins = apiConnectOrigins();

const cspDirectives = [
  "default-src 'self'",
  // unsafe-eval is required by Next.js dev server (webpack HMR); never in production
  isDev
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data: https:",
  isDev
    ? `connect-src 'self' http://localhost:8000 ws://localhost:3000 ${apiOrigins.join(" ")}`
    : `connect-src 'self' ${apiOrigins.join(" ")}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
];

const SECURITY_HEADERS = [
  { key: "X-Frame-Options",        value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy",        value: "strict-origin-when-cross-origin" },
  { key: "X-DNS-Prefetch-Control", value: "on" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  // HSTS: enforce HTTPS for 1 year in production (ignored on localhost)
  {
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  },
  {
    key: "Content-Security-Policy",
    value: cspDirectives.join("; "),
  },
];

const nextConfig: NextConfig = {
  // Proxy API calls through Next.js in dev (avoids CORS)
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/:path*`,
      },
    ];
  },

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: SECURITY_HEADERS,
      },
    ];
  },

  experimental: {
    // Server Actions for form submissions
    serverActions: {
      allowedOrigins: ["localhost:3000", "app.vantage.ai"],
    },
  },
};

export default nextConfig;
