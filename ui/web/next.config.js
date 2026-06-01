/** @type {import('next').NextConfig} */
const isVercel = process.env.VERCEL === "1";

// Gateway base — use 127.0.0.1 (IPv4) to avoid WSL wslrelay.exe grabbing [::1]:8000
const GATEWAY_URL = process.env.GATEWAY_URL || "http://127.0.0.1:8000";

const nextConfig = {
  ...(isVercel ? {} : { output: "standalone" }),
  env: {
    // Point all UI API calls to /api/gateway/* (same-origin, proxied below)
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "/api/gateway/ingress",
    NEXT_PUBLIC_CHAT_BASE: process.env.NEXT_PUBLIC_CHAT_BASE || "/api/gateway/chat",
    NEXT_PUBLIC_SUBMISSION_BASE: process.env.NEXT_PUBLIC_SUBMISSION_BASE || "/api/gateway/submission",
    NEXT_PUBLIC_WORKFLOW_BASE: process.env.NEXT_PUBLIC_WORKFLOW_BASE || "/api/gateway/workflow",
    NEXT_PUBLIC_KEYCLOAK_URL: process.env.NEXT_PUBLIC_KEYCLOAK_URL || "http://localhost:8080",
    NEXT_PUBLIC_KEYCLOAK_REALM: process.env.NEXT_PUBLIC_KEYCLOAK_REALM || "claimgpt",
    NEXT_PUBLIC_KEYCLOAK_CLIENT_ID: process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID || "claimgpt-web",
  },
  async rewrites() {
    return [
      {
        // Proxy /api/gateway/:path* → http://127.0.0.1:8000/:path*
        // Using 127.0.0.1 (IPv4) bypasses wslrelay.exe which sits on [::1]:8000
        source: "/api/gateway/:path*",
        destination: `${GATEWAY_URL}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
