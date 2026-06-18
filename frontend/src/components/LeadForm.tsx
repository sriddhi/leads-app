'use client';

import React, { useState } from 'react';
import Input from '@/components/ui/Input';
import Button from '@/components/ui/Button';
import { submitLead } from '@/lib/api';

const ACCEPTED_TYPES = [
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
];
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

type FieldErrors = Partial<
  Record<'first_name' | 'last_name' | 'email' | 'message' | 'resume', string>
>;

/**
 * Uncontrolled form: values are read from the DOM via FormData on submit and validated there.
 * This is deliberate — it is robust to browser autofill/paste, which don't reliably fire the
 * React change events that controlled/react-hook-form value tracking depends on (the cause of
 * "Required" showing on filled fields and a blocked submit).
 */
export default function LeadForm() {
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});

  function validate(fd: FormData): FieldErrors {
    const errs: FieldErrors = {};
    const first = String(fd.get('first_name') ?? '').trim();
    const last = String(fd.get('last_name') ?? '').trim();
    const email = String(fd.get('email') ?? '').trim();
    const message = String(fd.get('message') ?? '');
    const resume = fd.get('resume');

    if (!first) errs.first_name = 'First name is required';
    if (!last) errs.last_name = 'Last name is required';
    if (!EMAIL_RE.test(email)) errs.email = 'Please enter a valid email address';
    if (message.length > 2000) errs.message = 'Message must be under 2000 characters';

    const file = resume instanceof File && resume.size > 0 ? resume : null;
    if (!file) errs.resume = 'Resume is required';
    else if (!ACCEPTED_TYPES.includes(file.type)) errs.resume = 'Only .pdf, .doc, and .docx files are accepted';
    else if (file.size > MAX_FILE_SIZE) errs.resume = 'File must be under 20MB';

    return errs;
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setServerError(null);
    const form = e.currentTarget;
    const fd = new FormData(form);

    const errs = validate(fd);
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;

    // Drop the honeypot-free trimmed values back in (trim names/email server-side too).
    setSubmitting(true);
    try {
      // Remove an empty optional message so the backend stores NULL rather than "".
      if (!String(fd.get('message') ?? '').trim()) fd.delete('message');
      await submitLead(fd);
      setSubmitted(true);
    } catch (err) {
      setServerError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  // Clear a field's error as soon as the user edits it (so red only stays on still-bad fields).
  const clear = (field: keyof FieldErrors) => () =>
    setErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));

  if (submitted) {
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-6 text-center">
        <div className="mb-2 text-2xl">✓</div>
        <h3 className="text-lg font-semibold text-green-800">Application Submitted!</h3>
        <p className="mt-1 text-sm text-green-700">
          Thank you for your application. We will review it and get back to you shortly.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-4">
        <Input name="first_name" label="First Name" placeholder="Jane"
          error={errors.first_name} onChange={clear('first_name')} />
        <Input name="last_name" label="Last Name" placeholder="Doe"
          error={errors.last_name} onChange={clear('last_name')} />
      </div>

      <Input name="email" type="email" label="Email Address" placeholder="jane@example.com"
        autoComplete="email" error={errors.email} onChange={clear('email')} />

      <Input name="phone" type="tel" label="Phone" placeholder="(optional)"
        autoComplete="tel" />

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          Message <span className="font-normal text-gray-400">(optional)</span>
        </label>
        <textarea
          name="message"
          rows={3}
          placeholder="Anything you'd like the attorney to know, or a question…"
          onChange={clear('message')}
          className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        {errors.message && <p className="text-xs text-red-600">{errors.message}</p>}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">Resume</label>
        <input
          type="file"
          name="resume"
          accept=".pdf,.doc,.docx"
          onChange={clear('resume')}
          className={`block w-full text-sm text-gray-500 file:mr-4 file:rounded-md file:border-0 file:bg-blue-600 file:px-4 file:py-2 file:text-sm file:font-medium file:text-white hover:file:bg-blue-700 ${
            errors.resume ? 'rounded border border-red-500 p-1' : ''
          }`}
        />
        <p className="text-xs text-gray-400">PDF, DOC, or DOCX — max 20MB</p>
        {errors.resume && <p className="text-xs text-red-600">{errors.resume}</p>}
      </div>

      {serverError && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {serverError}
        </div>
      )}

      <Button type="submit" variant="primary" loading={submitting} className="w-full py-2.5">
        Submit Application
      </Button>
    </form>
  );
}
