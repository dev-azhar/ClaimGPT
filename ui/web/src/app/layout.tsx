import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "ClaimGPT",
  description: "AI-powered claims processing — submit and track your medical claims",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {/* Animated liquid-glass mesh background — pure CSS, no perf cost.
            Sits behind .app-shell; respects prefers-reduced-motion. */}
        <div className="liquid-bg" aria-hidden="true">
          <span className="blob blob-a" />
          <span className="blob blob-b" />
          <span className="blob blob-c" />
          <span className="grain" />
        </div>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
