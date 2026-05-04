import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { LanguageProvider } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "ClaimGPT — Claim processing for TPAs & insurers",
  description: "AI-assisted claim intake, validation, review and settlement workflow for Indian TPAs and insurers.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Add the suppression flag here
    <html lang="en" suppressHydrationWarning>
      <body>
        <LanguageProvider>
          <AuthProvider>{children}</AuthProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}