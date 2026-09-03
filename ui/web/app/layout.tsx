import './globals.css';
import type { Metadata } from 'next';
import { Inter, Outfit } from 'next/font/google';
import { DesignProvider } from '@/components/claimgpt/design-context';
import { DesignSwitcher } from '@/components/claimgpt/design-switcher';
import { Toaster } from '@/components/ui/toaster';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});
const outfit = Outfit({
  subsets: ['latin'],
  variable: '--font-outfit',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'ClaimsGuru | Enterprise · India',
  description:
    'AI-powered health insurance claim reimbursement & audit platform for India. OCR, ICD-10/CPT coding, validation, TPA submission, and audit in one unified workspace.',
  metadataBase: new URL('https://claimsguru.example.com'),
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${outfit.variable}`}>

      <body className="font-sans antialiased">
        <DesignProvider>
          {children}
          <DesignSwitcher />
          <Toaster />
        </DesignProvider>
      </body>
    </html>
  );
}
