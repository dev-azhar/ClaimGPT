import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";

export const metadata: Metadata = {
  title: "ClaimGPT",
  description: "AI-powered claims processing — submit and track your medical claims",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Add the suppression flag here
    <html lang="en" suppressHydrationWarning>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}