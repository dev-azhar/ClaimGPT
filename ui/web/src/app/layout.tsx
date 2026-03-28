import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ClaimGPT",
  description: "AI-powered claims processing — submit and track your medical claims",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
