/** @type {import('next').NextConfig} */
const isVercel = process.env.VERCEL === "1";

const nextConfig = {
  ...(isVercel ? {} : { output: "standalone" }),
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/ingress",
    NEXT_PUBLIC_CHAT_BASE: process.env.NEXT_PUBLIC_CHAT_BASE || "http://localhost:8000/chat",
    NEXT_PUBLIC_SUBMISSION_BASE: process.env.NEXT_PUBLIC_SUBMISSION_BASE || "http://localhost:8000/submission",
    NEXT_PUBLIC_WORKFLOW_BASE: process.env.NEXT_PUBLIC_WORKFLOW_BASE || "http://localhost:8000/workflow",
    NEXT_PUBLIC_KEYCLOAK_URL: process.env.NEXT_PUBLIC_KEYCLOAK_URL || "http://localhost:8080",
    NEXT_PUBLIC_KEYCLOAK_REALM: process.env.NEXT_PUBLIC_KEYCLOAK_REALM || "claimgpt",
    NEXT_PUBLIC_KEYCLOAK_CLIENT_ID: process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID || "claimgpt-web",
  },
};

module.exports = nextConfig;
