import type { Metadata } from 'next';
import './globals.css';
import DisclosureBanner from '@/components/DisclosureBanner';

export const metadata: Metadata = {
  title: 'Leads Management',
  description: 'Lead submission and management portal',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">
        <DisclosureBanner />
        {children}
      </body>
    </html>
  );
}
