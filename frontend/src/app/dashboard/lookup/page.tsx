'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { getToken } from '@/lib/auth';
import { getLeadByNumber, reverse, isConflictError } from '@/lib/api';
import Input from '@/components/ui/Input';
import Button from '@/components/ui/Button';
import Alert from '@/components/ui/Alert';
import StatusBadge from '@/components/StatusBadge';
import DuplicateBadge from '@/components/DuplicateBadge';
import Timeline from '@/components/Timeline';
import ReverseModal from '@/components/ReverseModal';
import { ToastContainer } from '@/components/ui/Toast';
import { useToast } from '@/lib/useToast';
import { formatDateTime } from '@/lib/format';
import type { LeadDetail } from '@/types';

export default function LookupPage() {
  const [query, setQuery] = useState('');
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reverseOpen, setReverseOpen] = useState(false);
  const { toasts, showToast, dismissToast } = useToast();

  async function doLookup(num: string) {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setLead(await getLeadByNumber(token, num));
    } catch (err) {
      setLead(null);
      setError(err instanceof Error ? err.message : 'Lookup failed.');
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    await doLookup(trimmed);
  }

  async function handleReverseSubmit(reason: string) {
    const token = getToken();
    if (!token || !lead) return;
    try {
      await reverse(token, lead.id, lead.version, reason);
      showToast(`Reversed ${lead.lead_number}.`, 'success');
      await doLookup(lead.lead_number);
    } catch (err) {
      if (isConflictError(err)) {
        showToast('This lead changed — reloading.', 'warning');
        await doLookup(lead.lead_number);
      }
      throw err;
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="mb-6 text-2xl font-bold text-gray-900">Lookup</h1>

      <form onSubmit={handleSubmit} className="mb-8 flex items-end gap-3">
        <div className="flex-1">
          <Input
            label="Lead Number"
            placeholder="e.g. L-1024"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <Button type="submit" variant="primary" loading={loading} className="py-2.5">
          Search
        </Button>
      </form>

      {error && <Alert variant="error">{error}</Alert>}

      {lead && (
        <div className="flex flex-col gap-6">
          {/* Header */}
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-bold text-gray-900">
                  {lead.first_name} {lead.last_name}
                </h2>
                <span className="text-sm text-gray-400">{lead.lead_number}</span>
              </div>
              <p className="mt-1 text-sm text-gray-500">{lead.email}</p>
            </div>
            <div className="flex items-center gap-2">
              {lead.is_potential_duplicate && <DuplicateBadge />}
              <StatusBadge status={lead.status} />
            </div>
          </div>

          {/* Detail card */}
          <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
            <dl className="divide-y divide-gray-100">
              <Row label="Lead Number" value={lead.lead_number} />
              <Row label="Assignee" value={lead.assignee_name ?? 'Unassigned'} />
              <Row label="Status" value={<StatusBadge status={lead.status} />} />
              {lead.duplicate_of && (
                <Row
                  label="Duplicate of"
                  value={
                    <Link
                      href={`/dashboard/${lead.duplicate_of}`}
                      className="text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      View original
                    </Link>
                  }
                />
              )}
              <Row label="Submitted" value={formatDateTime(lead.created_at)} />
            </dl>
          </div>

          {/* Timeline */}
          <div>
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
              Timeline
            </h3>
            <Timeline periods={lead.timeline} />
          </div>

          {/* Reverse action */}
          {lead.status === 'REACHED_OUT' && (
            <div>
              <Button variant="danger" onClick={() => setReverseOpen(true)}>
                Reverse Reached Out
              </Button>
            </div>
          )}

          <Link
            href={`/dashboard/${lead.id}`}
            className="text-sm text-blue-600 hover:text-blue-800 hover:underline"
          >
            Open full detail →
          </Link>
        </div>
      )}

      <ReverseModal
        open={reverseOpen}
        onClose={() => setReverseOpen(false)}
        onSubmit={handleReverseSubmit}
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-4 px-6 py-4">
      <dt className="text-sm font-medium text-gray-500">{label}</dt>
      <dd className="col-span-2 text-sm text-gray-900">{value}</dd>
    </div>
  );
}
