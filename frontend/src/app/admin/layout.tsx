'use client';

import React, { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import Link from 'next/link';
import { getToken, removeToken } from '@/lib/auth';
import { getMe } from '@/lib/api';
import Spinner from '@/components/ui/Spinner';
import type { User } from '@/types';

const navLinks = [
  { href: '/admin', label: 'Overview' },
  { href: '/admin/audit', label: 'Audit' },
  { href: '/admin/attorney-time', label: 'Attorney Time' },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.push('/login');
      return;
    }

    getMe(token)
      .then((me) => {
        if (me.role !== 'ADMIN') {
          router.push('/dashboard');
          return;
        }
        setUser(me);
        setChecking(false);
      })
      .catch(() => {
        removeToken();
        router.push('/login');
      });
  }, [router]);

  function handleLogout() {
    removeToken();
    router.push('/login');
  }

  function isActive(href: string): boolean {
    if (href === '/admin') return pathname === '/admin';
    return pathname.startsWith(href);
  }

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="sticky top-0 z-10 border-b border-gray-200 bg-white shadow-sm">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
          <div className="flex items-center gap-6">
            <span className="text-base font-semibold text-gray-900">Leads Admin</span>
            <nav className="flex items-center gap-1">
              {navLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    isActive(link.href)
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                  }`}
                >
                  {link.label}
                </Link>
              ))}
              <Link
                href="/dashboard"
                className="rounded-md px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900"
              >
                Attorney View
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-4">
            {user && <span className="text-sm text-gray-500">{user.email}</span>}
            <button
              onClick={handleLogout}
              className="rounded-md bg-gray-100 px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-200"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
    </div>
  );
}
