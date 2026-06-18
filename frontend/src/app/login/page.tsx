'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import Input from '@/components/ui/Input';
import Button from '@/components/ui/Button';
import { login, getMe } from '@/lib/api';
import { saveToken } from '@/lib/auth';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

type FieldErrors = Partial<Record<'email' | 'password', string>>;

export default function LoginPage() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  // Uncontrolled + FormData read on submit — robust to autofilled credentials, which don't
  // reliably fire the React change events controlled value tracking depends on.
  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setServerError(null);
    const fd = new FormData(e.currentTarget);
    const email = String(fd.get('email') ?? '').trim();
    const password = String(fd.get('password') ?? '');

    const errs: FieldErrors = {};
    if (!EMAIL_RE.test(email)) errs.email = 'Please enter a valid email address';
    if (!password) errs.password = 'Password is required';
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    setSubmitting(true);
    try {
      const token = await login(email, password);
      saveToken(token.access_token);
      const me = await getMe(token.access_token);
      router.push(me.role === 'ADMIN' ? '/admin' : '/dashboard');
    } catch (err) {
      setServerError(
        err instanceof Error ? err.message : 'Login failed. Please check your credentials.'
      );
    } finally {
      setSubmitting(false);
    }
  }

  const clear = (field: keyof FieldErrors) => () =>
    setErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        {/* Header */}
        <div className="rounded-t-xl bg-gradient-to-r from-gray-800 to-gray-900 px-8 py-8 text-white shadow-lg">
          <h1 className="text-2xl font-bold tracking-tight">Attorney Portal</h1>
          <p className="mt-1 text-sm text-gray-300">Sign in to manage your leads.</p>
        </div>

        {/* Form */}
        <div className="rounded-b-xl bg-white px-8 py-8 shadow-lg">
          <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
            <Input
              name="email"
              label="Email Address"
              type="email"
              placeholder="attorney@lawfirm.com"
              autoComplete="email"
              error={errors.email}
              onChange={clear('email')}
            />

            <Input
              name="password"
              label="Password"
              type="password"
              placeholder="••••••••"
              autoComplete="current-password"
              error={errors.password}
              onChange={clear('password')}
            />

            {serverError && (
              <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {serverError}
              </div>
            )}

            <Button type="submit" variant="primary" loading={submitting} className="w-full py-2.5">
              Sign In
            </Button>
          </form>
        </div>
      </div>
    </main>
  );
}
